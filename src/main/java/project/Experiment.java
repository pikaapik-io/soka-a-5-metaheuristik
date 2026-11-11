package project;

import ch.qos.logback.classic.Level;
import java.io.IOException;
import java.io.PrintWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.text.DecimalFormat;
import java.text.DecimalFormatSymbols;
import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.function.ToDoubleFunction;
import java.util.stream.Collectors;
import org.cloudbus.cloudsim.cloudlets.Cloudlet;
import org.cloudbus.cloudsim.datacenters.Datacenter;
import org.cloudbus.cloudsim.datacenters.DatacenterCharacteristics;
import org.cloudbus.cloudsim.hosts.Host;
import org.cloudbus.cloudsim.schedulers.cloudlet.CloudletScheduler;
import org.cloudbus.cloudsim.vms.Vm;
import org.cloudsimplus.util.Log;
import org.slf4j.LoggerFactory;
import project.data.GoCJLoader;
import project.metrics.EnergyMeter;
import project.metrics.MetricsCollector;
import project.metrics.Result;
import project.model.EnergyModel;
import project.model.ObjectiveFunction;
import project.scheduler.ClonalSelectionScheduler;
import project.scheduler.HarmonySearchScheduler;
import project.scheduler.MetaheuristicScheduler;
import project.setup.CloudSimAdapter;
import project.setup.DatacenterFactory;
import project.setup.SimulationSetup;

/**
 * Runs HS or CSA on the CloudSim Plus scenario of the project design.
 *
 * Usage: Experiment [dataset|-] [HS|CSA] [runs=10] [seed=42] [w=0.5] [budget=10000]
 *   "-" uses the 5-task sample. Run r uses seed + r - 1 and a new SimulationSetup.
 *   -Dlog=info shows the CloudSim log (default: error, because of the many runs).
 *   -Dout=folder writes the CSV files somewhere else (default: results/simulation).
 */
public final class Experiment {
	/** Output folder, -Dout=... to change it (e.g. for the determinism check). */
	private static final Path OUTPUT_DIR = Path.of(System.getProperty("out", "results/simulation"));
	private static final double[] SAMPLE = {900_000, 600_000, 450_000, 300_000, 150_000};

	private Experiment() { }

	/** One finished run: metrics from CloudSim plus the scheduler results. */
	private static final class Run {
		final int index;
		final long seed;
		final Result result;
		final double fitness;
		final long evaluations;
		final double analyticMakespan;
		final double analyticEnergyKwh;
		final double[] convergence;
		final SimulationSetup setup;

		Run(int index, long seed, Result result, MetaheuristicScheduler scheduler, int[] mapping,
			SimulationSetup setup) {
			this.index = index;
			this.seed = seed;
			this.result = result;
			this.fitness = scheduler.bestFitness();
			this.evaluations = scheduler.evaluationsUsed();
			ObjectiveFunction objective = scheduler.objective();
			this.analyticMakespan = objective.makespan(mapping);
			this.analyticEnergyKwh = EnergyMeter.toKwh(objective.energyJoules(mapping));
			this.convergence = scheduler.convergence();
			this.setup = setup;
		}
	}

	public static void main(String[] args) throws IOException {
		Log.setLevel(Level.toLevel(System.getProperty("log", "error"), Level.ERROR));
		// RAM/BW contention warnings are logged per cloudlet every tick and would flood the output.
		Log.setLevel(LoggerFactory.getLogger(CloudletScheduler.class.getSimpleName()), Level.ERROR);

		Path dataset = args.length == 0 || args[0].equals("-") ? null : Path.of(args[0]);
		double[] taskLengths = dataset == null ? SAMPLE.clone() : GoCJLoader.load(dataset);
		String algorithm = args.length > 1 ? args[1].toUpperCase(Locale.ROOT) : "HS";
		int runs = args.length > 2 ? Integer.parseInt(args[2]) : 10;
		long baseSeed = args.length > 3 ? Long.parseLong(args[3]) : 42;
		double weight = args.length > 4 ? Double.parseDouble(args[4]) : MetaheuristicScheduler.DEFAULT_WEIGHT;
		int budget = args.length > 5 ? Integer.parseInt(args[5]) : MetaheuristicScheduler.DEFAULT_BUDGET;
		if (!algorithm.equals("HS") && !algorithm.equals("CSA")) {
			throw new IllegalArgumentException("Algorithm must be HS or CSA, got " + algorithm);
		}
		if (runs < 1) {
			throw new IllegalArgumentException("runs must be at least 1");
		}
		String datasetName = dataset == null ? "sample"
				: dataset.getFileName().toString().replaceFirst("\\.txt$", "");

		// JIT warm-up for metric 8 (scheduling time), same idea as the KPB runner.
		SimulationSetup warmUp = new SimulationSetup(taskLengths);
		create(algorithm, CloudSimAdapter.energyModel(warmUp), baseSeed, weight, budget)
				.schedule(taskLengths, CloudSimAdapter.vmCapacities(warmUp.vmList()));

		System.out.printf(Locale.US, "scheduler=%s dataset=%s tasks=%d runs=%d seed=%d..%d w=%s budget=%d%n",
				describe(algorithm, taskLengths.length), datasetName, taskLengths.length, runs, baseSeed,
				baseSeed + runs - 1, format(weight), budget);

		List<Run> results = new ArrayList<>();
		for (int r = 1; r <= runs; r++) {
			long seed = baseSeed + r - 1;
			// ★ TUNJUK: setiap run memakai SimulationSetup baru dan seed = seed dasar + run - 1.
			SimulationSetup setup = new SimulationSetup(taskLengths);
			EnergyModel energyModel = CloudSimAdapter.energyModel(setup);
			double[] vmCapacities = CloudSimAdapter.vmCapacities(setup.vmList());
			MetaheuristicScheduler scheduler = create(algorithm, energyModel, seed, weight, budget);

			long start = System.nanoTime();
			int[] mapping = scheduler.schedule(taskLengths, vmCapacities);
			double schedulingMillis = (System.nanoTime() - start) / 1e6;

			setup.run(mapping);
			Result result = MetricsCollector.collect(scheduler.getName(), setup, schedulingMillis);
			Run run = new Run(r, seed, result, scheduler, mapping, setup);
			results.add(run);

			if (r == 1) {
				printInfrastructure(setup);
			}
			printRun(run, runs, setup);
			if (taskLengths.length <= 20) {
				System.out.println("  mapping=" + Arrays.toString(mapping));
			}
		}
		Map<String, double[]> stats = printAggregate(results);

		if (dataset != null) {
			writeCsv(datasetName, algorithm, weight, budget, results, stats);
			System.out.printf("hasil -> %s/summary.csv, aggregate.csv, cloudlets_%s_%s_w%s_run*.csv, "
					+ "convergence_%s_%s_w%s_run*.csv%n", OUTPUT_DIR, datasetName, algorithm, format(weight),
					datasetName, algorithm, format(weight));
		}
	}

	private static MetaheuristicScheduler create(String algorithm, EnergyModel energyModel, long seed,
												 double weight, int budget) {
		return algorithm.equals("HS")
				? new HarmonySearchScheduler(energyModel, seed, weight, budget)
				: new ClonalSelectionScheduler(energyModel, seed, weight, budget);
	}

	private static String describe(String algorithm, int taskCount) {
		return algorithm.equals("HS")
				? String.format(Locale.US, "HS(HMS=%d, HMCR=%s, PAR=%s)", HarmonySearchScheduler.DEFAULT_HMS,
						format(HarmonySearchScheduler.DEFAULT_HMCR), format(HarmonySearchScheduler.DEFAULT_PAR))
				: String.format(Locale.US, "CSA(N=%d, n=%d, beta=%s, d=%d, maxMut=%d)",
						ClonalSelectionScheduler.DEFAULT_POPULATION, ClonalSelectionScheduler.DEFAULT_SELECTED,
						format(ClonalSelectionScheduler.DEFAULT_CLONE_FACTOR), ClonalSelectionScheduler.DEFAULT_REPLACED,
						ClonalSelectionScheduler.maxMutation(taskCount));
	}

	private static void printRun(Run run, int runs, SimulationSetup setup) {
		Result r = run.result;
		System.out.printf(Locale.US, "[run %d/%d seed=%d] fitness=%.6f evaluations=%d | tasks=%d, vmsCreated=%d/%d, "
						+ "cloudletsFinished=%d/%d%n", run.index, runs, run.seed, run.fitness, run.evaluations,
				r.tasks(), setup.broker().getVmCreatedList().size(), setup.vmList().size(),
				setup.cloudlets().stream().filter(Cloudlet::isFinished).count(), r.tasks());
		System.out.printf(Locale.US, "  makespan=%.3f s (analitik %.3f s), energy=%.4f kWh (analitik %.4f kWh), "
						+ "avgResponse=%.3f s%n", r.makespan(), run.analyticMakespan, r.energyKwh(),
				run.analyticEnergyKwh, r.averageResponse());
		System.out.printf(Locale.US, "  utilization=%.2f%%, DI=%.4f (VM terpakai %.4f), throughput=%.4f task/s, "
						+ "cost=$%.2f, schedulingTime=%.3f ms%n", r.utilizationPercent(), r.degreeOfImbalance(),
				r.degreeOfImbalanceUsedVms(), r.throughput(), r.totalCost(), r.schedulingMillis());
	}

	/** Metrics reported as mean +/- std (sample std, n - 1) over the runs. */
	private static Map<String, double[]> printAggregate(List<Run> runs) {
		Map<String, ToDoubleFunction<Run>> metrics = new LinkedHashMap<>();
		metrics.put("fitness", run -> run.fitness);
		metrics.put("makespan_s", run -> run.result.makespan());
		metrics.put("analytic_makespan_s", run -> run.analyticMakespan);
		metrics.put("energy_kwh", run -> run.result.energyKwh());
		metrics.put("analytic_energy_kwh", run -> run.analyticEnergyKwh);
		metrics.put("avg_response_s", run -> run.result.averageResponse());
		metrics.put("utilization_pct", run -> run.result.utilizationPercent());
		metrics.put("di_all_vm", run -> run.result.degreeOfImbalance());
		metrics.put("di_used_vm", run -> run.result.degreeOfImbalanceUsedVms());
		metrics.put("throughput_task_s", run -> run.result.throughput());
		metrics.put("cost_usd", run -> run.result.totalCost());
		metrics.put("scheduling_ms", run -> run.result.schedulingMillis());

		Map<String, double[]> stats = new LinkedHashMap<>();
		System.out.printf("rata-rata ± std dari %d run:%n", runs.size());
		for (Map.Entry<String, ToDoubleFunction<Run>> metric : metrics.entrySet()) {
			double[] values = runs.stream().mapToDouble(metric.getValue()).toArray();
			double mean = Arrays.stream(values).average().orElse(0);
			double std = 0;
			if (values.length > 1) {
				double squares = Arrays.stream(values).map(v -> (v - mean) * (v - mean)).sum();
				std = Math.sqrt(squares / (values.length - 1));
			}
			stats.put(metric.getKey(), new double[] {mean, std});
			System.out.printf(Locale.US, "  %-20s %14.4f ± %.4f%n", metric.getKey(), mean, std);
		}
		return stats;
	}

	/** Datacenter, host and VM specs read back from the CloudSim objects, to compare with the design. */
	private static void printInfrastructure(SimulationSetup setup) {
		System.out.println("=== Infrastruktur CloudSim ===");
		for (Datacenter dc : setup.datacenters()) {
			DatacenterCharacteristics ch = dc.getCharacteristics();
			String name = DatacenterFactory.typeOf(dc.getHost(0)) == DatacenterFactory.HostType.A_PERFORMANCE
					? "Performance" : "Efficiency";
			System.out.printf(Locale.US, "DC-%d %s | %s / %s / %s | %d host | $%.2f/s, $%.2f/GB RAM, "
							+ "$%.4f/GB storage, $%.3f/Mbps BW%n",
					dc.getId(), name, ch.getArchitecture(), ch.getOs(), ch.getVmm(), dc.getHostList().size(),
					ch.getCostPerSecond(), ch.getCostPerMem() * 1024, ch.getCostPerStorage() * 1024,
					ch.getCostPerBw());
			for (Host host : dc.getHostList()) {
				// VMs are already deallocated when the simulation ends, so group by vm.getHost().
				List<Vm> vms = setup.vmList().stream().filter(vm -> vm.getHost() == host).collect(Collectors.toList());
				long usedPes = vms.stream().mapToLong(Vm::getNumberOfPes).sum();
				System.out.printf(Locale.US, "  Host %d | %d PE x %.0f MIPS | RAM %d GB | BW %d Mbps | "
								+ "P idle %.0f W, P max %.0f W | PE terpakai %d/%d%n",
						host.getId(), host.getNumberOfPes(), host.getMips(), host.getRam().getCapacity() / 1024,
						host.getBw().getCapacity(), host.getPowerModel().getPower(0),
						host.getPowerModel().getPower(1), usedPes, host.getNumberOfPes());
				for (Vm vm : vms) {
					System.out.printf(Locale.US, "    vm%-2d %s | %d PE x %.0f MIPS | RAM %d GB | BW %d Mbps%n",
							vm.getId(), vm.getDescription(), vm.getNumberOfPes(), vm.getMips(),
							vm.getRam().getCapacity() / 1024, vm.getBw().getCapacity());
				}
			}
		}
		EnergyModel energy = CloudSimAdapter.energyModel(setup);
		System.out.printf(Locale.US, "Total: %d datacenter, %d host, %d VM | sum P_idle = %.0f W, "
						+ "kappa DC-1 = %.6f J/MI, kappa DC-2 = %.6f J/MI%n%n",
				setup.datacenters().size(), setup.hosts().size(), setup.vmList().size(), energy.idleWatts(),
				energy.joulePerMi(0), energy.joulePerMi(setup.vmList().size() - 1));
	}

	/** Weight in file names and CSV, e.g. 0.5 -> "0.5" (always with a dot). */
	static String format(double value) {
		return new DecimalFormat("0.##", DecimalFormatSymbols.getInstance(Locale.US)).format(value);
	}

	private static void writeCsv(String dataset, String algorithm, double weight, int budget, List<Run> runs,
								 Map<String, double[]> stats) throws IOException {
		Files.createDirectories(OUTPUT_DIR);
		String tag = String.format("%s_%s_w%s", dataset, algorithm, format(weight));

		Path summary = OUTPUT_DIR.resolve("summary.csv");
		boolean newSummary = !Files.exists(summary);
		try (PrintWriter out = new PrintWriter(Files.newBufferedWriter(summary,
				StandardOpenOption.CREATE, StandardOpenOption.APPEND))) {
			if (newSummary) {
				out.println("timestamp,dataset,tasks,algorithm,w,budget,run,seed,fitness,evaluations,"
						+ "makespan_s,analytic_makespan_s,energy_kwh,analytic_energy_kwh,avg_response_s,"
						+ "utilization_pct,di_all_vm,di_used_vm,throughput_task_s,cost_usd,scheduling_ms");
			}
			String timestamp = LocalDateTime.now().truncatedTo(ChronoUnit.SECONDS).toString();
			for (Run run : runs) {
				Result r = run.result;
				out.printf(Locale.US, "%s,%s,%d,%s,%s,%d,%d,%d,%.10f,%d,%.4f,%.4f,%.6f,%.6f,%.4f,%.2f,%.4f,%.4f,"
								+ "%.4f,%.4f,%.3f%n",
						timestamp, dataset, r.tasks(), algorithm, format(weight), budget, run.index, run.seed,
						run.fitness, run.evaluations, r.makespan(), run.analyticMakespan, r.energyKwh(),
						run.analyticEnergyKwh, r.averageResponse(), r.utilizationPercent(), r.degreeOfImbalance(),
						r.degreeOfImbalanceUsedVms(), r.throughput(), r.totalCost(), r.schedulingMillis());
			}
		}

		Path aggregate = OUTPUT_DIR.resolve("aggregate.csv");
		boolean newAggregate = !Files.exists(aggregate);
		try (PrintWriter out = new PrintWriter(Files.newBufferedWriter(aggregate,
				StandardOpenOption.CREATE, StandardOpenOption.APPEND))) {
			if (newAggregate) {
				StringBuilder header = new StringBuilder("timestamp,dataset,tasks,algorithm,w,budget,runs,seed_first");
				stats.keySet().forEach(key -> header.append(',').append(key).append("_mean,")
						.append(key).append("_std"));
				out.println(header);
			}
			StringBuilder row = new StringBuilder(String.format(Locale.US, "%s,%s,%d,%s,%s,%d,%d,%d",
					LocalDateTime.now().truncatedTo(ChronoUnit.SECONDS), dataset, runs.get(0).result.tasks(),
					algorithm, format(weight), budget, runs.size(), runs.get(0).seed));
			stats.values().forEach(v -> row.append(String.format(Locale.US, ",%.6f,%.6f", v[0], v[1])));
			out.println(row);
		}

		try (PrintWriter out = new PrintWriter(Files.newBufferedWriter(OUTPUT_DIR.resolve("placement.csv")))) {
			out.println("vm,vm_type,pes,mips_per_pe,ram_mb,bw_mbps,datacenter,host");
			for (Vm vm : runs.get(0).setup.vmList()) {
				out.printf(Locale.US, "%d,%s,%d,%.0f,%d,%d,%d,%d%n", vm.getId(), vm.getDescription(),
						vm.getNumberOfPes(), vm.getMips(), vm.getRam().getCapacity(), vm.getBw().getCapacity(),
						vm.getHost().getDatacenter().getId(), vm.getHost().getId());
			}
		}

		for (Run run : runs) {
			Path detail = OUTPUT_DIR.resolve(String.format("cloudlets_%s_run%d.csv", tag, run.index));
			try (PrintWriter out = new PrintWriter(Files.newBufferedWriter(detail))) {
				out.println("task_id,length_mi,vm,vm_type,datacenter,host,start_s,finish_s");
				for (Cloudlet c : run.setup.cloudlets()) {
					Vm vm = c.getVm();
					// getTotalLength() is length per PE x PE; the dataset value is what the scheduler saw.
					out.printf(Locale.US, "%d,%d,%d,%s,%d,%d,%.4f,%.4f%n", c.getId(), c.getTotalLength(), vm.getId(),
							vm.getDescription(), vm.getHost().getDatacenter().getId(), vm.getHost().getId(),
							c.getExecStartTime(), c.getFinishTime());
				}
			}

			// Step function of the best fitness: one row per improvement plus the last evaluation.
			// Double.toString is the shortest exact form, so verify_mapping.py can compare it with ==.
			Path convergence = OUTPUT_DIR.resolve(String.format("convergence_%s_run%d.csv", tag, run.index));
			try (PrintWriter out = new PrintWriter(Files.newBufferedWriter(convergence))) {
				out.println("evaluation,best_fitness");
				double[] trace = run.convergence;
				for (int e = 0; e < trace.length; e++) {
					if (e == 0 || trace[e] != trace[e - 1] || e == trace.length - 1) {
						out.println((e + 1) + "," + trace[e]);
					}
				}
			}
		}
	}
}
