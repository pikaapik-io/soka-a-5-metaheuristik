package project.scheduler;

import java.util.Arrays;
import project.model.EnergyModel;

/**
 * Clonal Selection Algorithm, CLONALG optimisation version (de Castro & Von Zuben, 2002).
 * Antibody = task -> VM vector, affinity = F(x) (smaller is better).
 *
 * The exp(-rho x f) mutation rate of CLONALG is replaced by an integer rule linear in the
 * rank (1 gene for the best antibody up to maxMut for rank n), so no libm function is
 * needed and the Python port stays bit-identical. The budget is checked before every
 * evaluation, so the run stops exactly at the budget, even in the middle of a generation.
 */
public final class ClonalSelectionScheduler extends MetaheuristicScheduler {

	public static final int DEFAULT_POPULATION = 20;
	public static final int DEFAULT_SELECTED = 10;
	public static final double DEFAULT_CLONE_FACTOR = 1.0;
	public static final int DEFAULT_REPLACED = 2;

	private final int populationSize;
	private final int selected;
	private final double cloneFactor;
	private final int replaced;

	public ClonalSelectionScheduler(EnergyModel energyModel, long seed, double weight, int maxEvaluations) {
		this(energyModel, seed, weight, maxEvaluations,
				DEFAULT_POPULATION, DEFAULT_SELECTED, DEFAULT_CLONE_FACTOR, DEFAULT_REPLACED);
	}

	public ClonalSelectionScheduler(EnergyModel energyModel, long seed, double weight, int maxEvaluations,
									int populationSize, int selected, double cloneFactor, int replaced) {
		super(energyModel, seed, weight, maxEvaluations);
		if (populationSize < 2 || populationSize > maxEvaluations) {
			throw new IllegalArgumentException("N must be in the range [2, budget]");
		}
		if (selected < 1 || replaced < 0 || selected + replaced > populationSize) {
			throw new IllegalArgumentException("Need 1 <= n and n + d <= N, so elites are never replaced");
		}
		if (!Double.isFinite(cloneFactor) || cloneFactor <= 0) {
			throw new IllegalArgumentException("beta must be positive");
		}
		this.populationSize = populationSize;
		this.selected = selected;
		this.cloneFactor = cloneFactor;
		this.replaced = replaced;
	}

	@Override
	public String getName() {
		return "CSA";
	}

	/** maxMut = max(1, n_task / 20): 5 genes in S1, 25 in S2, 50 in S3. */
	public static int maxMutation(int taskCount) {
		return Math.max(1, taskCount / 20);
	}

	/** floor(beta x N / rank), at least one clone; rank starts at 0 here. */
	public int cloneCount(int rank) {
		return Math.max(1, (int) (cloneFactor * populationSize / (rank + 1)));
	}

	/** Linear in the rank: 1 gene for rank 0 up to maxMut for rank n-1. */
	public int mutationCount(int rank, int maxMutation) {
		return 1 + rank * (maxMutation - 1) / Math.max(1, selected - 1);
	}

	@Override
	protected int[] search(int taskCount) {
		int maxMutation = maxMutation(taskCount);
		int[][] population = new int[populationSize][];
		double[] affinity = new double[populationSize];
		for (int k = 0; k < populationSize; k++) {
			population[k] = randomSolution(taskCount);
			affinity[k] = evaluate(population[k]);
		}

		while (budgetLeft()) {
			// ★ TUNJUK: Langkah 1 - urutkan berdasarkan affinity (stabil, seri -> indeks kecil dulu).
			sortByAffinity(population, affinity);

			// ★ TUNJUK: Langkah 2-5 - n terbaik dikloning (ranking r -> floor(beta*N/r) klon),
			// klon dihipermutasi m_r gen, klon terbaik menggantikan induk hanya bila lebih baik.
			for (int rank = 0; rank < selected && budgetLeft(); rank++) {
				int clones = cloneCount(rank);
				int mutations = mutationCount(rank, maxMutation);
				int[] bestClone = null;
				double bestAffinity = affinity[rank];
				for (int c = 0; c < clones && budgetLeft(); c++) {
					int[] clone = population[rank].clone();
					for (int k = 0; k < mutations; k++) {
						int gene = random().nextInt(taskCount);
						clone[gene] = randomVm();
					}
					double cloneAffinity = evaluate(clone);
					if (cloneAffinity < bestAffinity) {
						bestAffinity = cloneAffinity;
						bestClone = clone;
					}
				}
				if (bestClone != null) {
					population[rank] = bestClone;
					affinity[rank] = bestAffinity;
				}
			}

			// ★ TUNJUK: Langkah 6 - receptor editing: d antibodi terburuk diganti antibodi acak.
			for (int k = populationSize - replaced; k < populationSize && budgetLeft(); k++) {
				population[k] = randomSolution(taskCount);
				affinity[k] = evaluate(population[k]);
			}
		}
		return population[argMin(affinity)];
	}

	/** Stable sort by (affinity, index), the same key as the Python port. */
	private static void sortByAffinity(int[][] population, double[] affinity) {
		Integer[] order = new Integer[population.length];
		for (int k = 0; k < order.length; k++) {
			order[k] = k;
		}
		Arrays.sort(order, (left, right) -> {
			int byAffinity = Double.compare(affinity[left], affinity[right]);
			return byAffinity != 0 ? byAffinity : Integer.compare(left, right);
		});
		int[][] sortedPopulation = new int[population.length][];
		double[] sortedAffinity = new double[affinity.length];
		for (int k = 0; k < order.length; k++) {
			sortedPopulation[k] = population[order[k]];
			sortedAffinity[k] = affinity[order[k]];
		}
		System.arraycopy(sortedPopulation, 0, population, 0, population.length);
		System.arraycopy(sortedAffinity, 0, affinity, 0, affinity.length);
	}

	public int populationSize() { return populationSize; }
	public int selected() { return selected; }
	public double cloneFactor() { return cloneFactor; }
	public int replaced() { return replaced; }
}
