package project.scheduler;

import java.util.Arrays;
import java.util.Random;
import project.model.EnergyModel;
import project.model.ObjectiveFunction;

/**
 * Common part of HS and CSA: seed, weight w, evaluation budget, capacity-proportional
 * random VM, and the convergence trace (best fitness after every evaluation).
 *
 * Determinism rule (design section 7): the search may only use Random.nextInt(bound) and
 * Random.nextDouble(), and no exp/pow/log, so realworld/metaheuristic.py can repeat every
 * step bit for bit. A new Random(seed) is created on every schedule() call, so calling it
 * twice with the same seed returns the same mapping.
 */
public abstract class MetaheuristicScheduler implements Scheduler {

	public static final int DEFAULT_BUDGET = 10_000;
	public static final double DEFAULT_WEIGHT = 0.5;

	private final EnergyModel energyModel;
	private final long seed;
	private final double weight;
	private final int maxEvaluations;

	private Random random;
	private ObjectiveFunction objective;
	private double[] cumulativeShare;
	private double[] trace;
	private int traceSize;
	private double bestFitness;
	private int[] bestMapping;

	protected MetaheuristicScheduler(EnergyModel energyModel, long seed, double weight, int maxEvaluations) {
		if (energyModel == null) {
			throw new IllegalArgumentException("An energy model is required");
		}
		if (!Double.isFinite(weight) || weight < 0 || weight > 1) {
			throw new IllegalArgumentException("w must be in the range [0, 1]");
		}
		if (maxEvaluations < 1) {
			throw new IllegalArgumentException("The evaluation budget must be positive");
		}
		this.energyModel = energyModel;
		this.seed = seed;
		this.weight = weight;
		this.maxEvaluations = maxEvaluations;
	}

	@Override
	public final int[] schedule(double[] taskLength, double[] vmCapacity) {
		validate(taskLength, vmCapacity);
		objective = new ObjectiveFunction(taskLength, vmCapacity, energyModel, weight);
		random = new Random(seed);
		cumulativeShare = cumulativeShare(vmCapacity);
		trace = new double[maxEvaluations];
		traceSize = 0;
		bestFitness = Double.POSITIVE_INFINITY;
		bestMapping = search(taskLength.length).clone();
		return bestMapping.clone();
	}

	/** Runs the metaheuristic and returns the best mapping found within the budget. */
	protected abstract int[] search(int taskCount);

	// ── Helpers for subclasses ───────────────────────────────────────────────

	/** F(x), recorded in the convergence trace. */
	protected final double evaluate(int[] mapping) {
		if (!budgetLeft()) {
			throw new IllegalStateException("Evaluation budget exhausted");
		}
		double fitness = objective.evaluate(mapping);
		if (fitness < bestFitness) {
			bestFitness = fitness;
		}
		trace[traceSize++] = bestFitness;
		return fitness;
	}

	protected final boolean budgetLeft() {
		return objective.evaluations() < maxEvaluations;
	}

	protected final int maxEvaluations() { return maxEvaluations; }
	protected final Random random() { return random; }

	// ★ TUNJUK: VM acak proporsional kapasitas (V3 13,9%, V2 4,2%, V1 1,4%), bukan seragam.
	/** VM drawn with probability C_j / sum C (one nextDouble call). */
	protected final int randomVm() {
		double r = random.nextDouble();
		for (int vm = 0; vm < cumulativeShare.length; vm++) {
			if (r < cumulativeShare[vm]) {
				return vm;
			}
		}
		return cumulativeShare.length - 1;
	}

	/** A random solution: randomVm() for task 0, 1, ..., n-1. */
	protected final int[] randomSolution(int taskCount) {
		int[] mapping = new int[taskCount];
		for (int task = 0; task < taskCount; task++) {
			mapping[task] = randomVm();
		}
		return mapping;
	}

	/** Index of the smallest value; the first index wins ties. */
	protected static int argMin(double[] values) {
		int best = 0;
		for (int k = 1; k < values.length; k++) {
			if (values[k] < values[best]) {
				best = k;
			}
		}
		return best;
	}

	/** Index of the largest value; the first index wins ties. */
	protected static int argMax(double[] values) {
		int worst = 0;
		for (int k = 1; k < values.length; k++) {
			if (values[k] > values[worst]) {
				worst = k;
			}
		}
		return worst;
	}

	private static double[] cumulativeShare(double[] vmCapacity) {
		double total = 0;
		for (double capacity : vmCapacity) {
			total += capacity;
		}
		double[] share = new double[vmCapacity.length];
		double prefix = 0;
		for (int vm = 0; vm < vmCapacity.length; vm++) {
			prefix += vmCapacity[vm];
			share[vm] = prefix / total;
		}
		return share;
	}

	private static void validate(double[] taskLength, double[] vmCapacity) {
		if (taskLength == null || taskLength.length == 0 || vmCapacity == null || vmCapacity.length == 0) {
			throw new IllegalArgumentException("At least one task and one VM are required");
		}
		for (double length : taskLength) {
			if (!Double.isFinite(length) || length < 0) {
				throw new IllegalArgumentException("Task lengths must be finite and non-negative");
			}
		}
		for (double capacity : vmCapacity) {
			if (!Double.isFinite(capacity) || capacity <= 0) {
				throw new IllegalArgumentException("VM capacities must be finite and positive");
			}
		}
	}

	// ── Results of the last schedule() call ─────────────────────────────────

	public long seed() { return seed; }
	public double weight() { return weight; }
	public double bestFitness() { return bestFitness; }
	public long evaluationsUsed() { return objective.evaluations(); }
	public ObjectiveFunction objective() { return objective; }

	/** trace[e] = best fitness after evaluation e + 1. */
	public double[] convergence() {
		return Arrays.copyOf(trace, traceSize);
	}
}
