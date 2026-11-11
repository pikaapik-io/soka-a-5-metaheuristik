package project.metrics;

import java.util.Arrays;
import java.util.List;
import org.cloudbus.cloudsim.cloudlets.Cloudlet;
import org.cloudbus.cloudsim.vms.Vm;
import org.cloudbus.cloudsim.vms.VmCost;
import project.setup.SimulationSetup;

/** Computes the design metrics (section 4.1) from a finished CloudSim run. */
public final class MetricsCollector {
	private MetricsCollector() { }

	public static Result collect(String scheduler, SimulationSetup setup, double schedulingMillis) {
		List<Cloudlet> cloudlets = setup.cloudlets();
		List<Vm> vms = setup.vmList();

		// T_j: finish time of the last cloudlet on VM j (all tasks arrive at t = 0)
		double[] vmFinish = new double[vms.size()];
		double totalResponse = 0;
		for (Cloudlet cloudlet : cloudlets) {
			int vm = vms.indexOf(cloudlet.getVm());
			vmFinish[vm] = Math.max(vmFinish[vm], cloudlet.getFinishTime());
			totalResponse += cloudlet.getFinishTime() - cloudlet.getSubmissionDelay();
		}
		double makespan = Arrays.stream(vmFinish).max().orElse(0);

		double energyJoules = Arrays.stream(setup.energyMeter().hostJoules(makespan)).sum();

		// Metric 7: CPU + RAM + bandwidth cost (storage cost is not part of the metric)
		double cost = 0;
		for (Vm vm : vms) {
			VmCost vmCost = new VmCost(vm);
			cost += vmCost.getProcessingCost() + vmCost.getMemoryCost() + vmCost.getBwCost();
		}

		return new Result(scheduler, cloudlets.size(), makespan,
				EnergyMeter.toKwh(energyJoules),
				cloudlets.isEmpty() ? 0 : totalResponse / cloudlets.size(),
				makespan == 0 ? 0 : 100 * Arrays.stream(vmFinish).sum() / (vms.size() * makespan),
				degreeOfImbalance(vmFinish),
				degreeOfImbalance(Arrays.stream(vmFinish).filter(t -> t > 0).toArray()),
				makespan == 0 ? 0 : cloudlets.size() / makespan,
				cost, schedulingMillis, vmFinish);
	}

	/** (T_max - T_min) / T_avg */
	static double degreeOfImbalance(double[] times) {
		if (times.length == 0) return 0;
		double avg = Arrays.stream(times).average().orElse(0);
		if (avg == 0) return 0;
		return (Arrays.stream(times).max().getAsDouble() - Arrays.stream(times).min().getAsDouble()) / avg;
	}
}
