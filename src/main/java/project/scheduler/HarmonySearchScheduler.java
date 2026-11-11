package project.scheduler;

import project.model.EnergyModel;

/**
 * Harmony Search (Geem, Kim & Loganathan, 2001) for the discrete task -> VM vector,
 * with the Global-best HS pitch adjustment (Omran & Mahdavi, 2008): the pitch-adjusted
 * gene is taken from the best harmony, because VM indices have no meaningful distance.
 *
 * One iteration builds one new harmony and costs one evaluation, so HMS + (budget - HMS)
 * iterations use exactly the whole budget.
 */
public final class HarmonySearchScheduler extends MetaheuristicScheduler {

	public static final int DEFAULT_HMS = 20;
	public static final double DEFAULT_HMCR = 0.98;
	public static final double DEFAULT_PAR = 0.5;

	private final int hms;
	private final double hmcr;
	private final double par;

	public HarmonySearchScheduler(EnergyModel energyModel, long seed, double weight, int maxEvaluations) {
		this(energyModel, seed, weight, maxEvaluations, DEFAULT_HMS, DEFAULT_HMCR, DEFAULT_PAR);
	}

	public HarmonySearchScheduler(EnergyModel energyModel, long seed, double weight, int maxEvaluations,
								  int hms, double hmcr, double par) {
		super(energyModel, seed, weight, maxEvaluations);
		if (hms < 2 || hms > maxEvaluations) {
			throw new IllegalArgumentException("HMS must be in the range [2, budget]");
		}
		if (!(hmcr >= 0 && hmcr <= 1) || !(par >= 0 && par <= 1)) {
			throw new IllegalArgumentException("HMCR and PAR must be in the range [0, 1]");
		}
		this.hms = hms;
		this.hmcr = hmcr;
		this.par = par;
	}

	@Override
	public String getName() {
		return "HS";
	}

	@Override
	protected int[] search(int taskCount) {
		// ★ TUNJUK: Langkah 1 - Harmony Memory berisi HMS vektor acak, masing-masing dievaluasi.
		int[][] memory = new int[hms][];
		double[] fitness = new double[hms];
		for (int h = 0; h < hms; h++) {
			memory[h] = randomSolution(taskCount);
			fitness[h] = evaluate(memory[h]);
		}

		for (int iteration = hms; iteration < maxEvaluations(); iteration++) {
			int best = argMin(fitness);
			// ★ TUNJUK: Langkah 2 - improvisasi per task i: memory consideration (HMCR),
			// pitch adjustment ke harmoni terbaik (PAR), atau random consideration.
			int[] harmony = new int[taskCount];
			for (int task = 0; task < taskCount; task++) {
				int vm;
				if (random().nextDouble() < hmcr) {
					vm = memory[random().nextInt(hms)][task];
					if (random().nextDouble() < par) {
						vm = memory[best][task];
					}
				} else {
					vm = randomVm();
				}
				harmony[task] = vm;
			}
			// ★ TUNJUK: Langkah 3 - harmoni baru menggantikan harmoni terburuk bila lebih baik.
			double newFitness = evaluate(harmony);
			int worst = argMax(fitness);
			if (newFitness < fitness[worst]) {
				memory[worst] = harmony;
				fitness[worst] = newFitness;
			}
		}
		return memory[argMin(fitness)];
	}

	public int hms() { return hms; }
	public double hmcr() { return hmcr; }
	public double par() { return par; }
}
