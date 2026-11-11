package project.model;

/**
 * Fitness of a task -> VM mapping (design section 3), minimised:
 *
 *   F(x) = w x Cmax(x) / C_LB + (1 - w) x E(x) / E_LB
 *   Cmax(x) = max_j sum_{i : x_i = j} L_i / C_j
 *   E(x)    = Cmax(x) x sum P_idle + sum_i kappa_{x_i} x L_i
 *   C_LB    = sum L_i / sum C_j,   E_LB = C_LB x sum P_idle + kappa_min x sum L_i
 *
 * Both terms are >= 1, so F = 1 is the theoretical optimum. The bounds depend only on the
 * instance, so F does not change between iterations (unlike per-population min-max).
 *
 * The floating point operations are written in a fixed order: realworld/metaheuristic.py
 * repeats them line by line so that Java and Python give bit-identical fitness values.
 */
public final class ObjectiveFunction {
	private final double[] taskLength;
	private final double[] vmCapacity;
	private final EnergyModel energyModel;
	private final double weight;
	private final double makespanLowerBound;
	private final double energyLowerBound;
	private long evaluations;

	public ObjectiveFunction(double[] taskLength, double[] vmCapacity, EnergyModel energyModel, double weight) {
		if (taskLength == null || vmCapacity == null || vmCapacity.length == 0) {
			throw new IllegalArgumentException("Tasks and at least one VM are required");
		}
		if (energyModel == null || energyModel.vmCount() != vmCapacity.length) {
			throw new IllegalArgumentException("The energy model must cover every VM");
		}
		if (!Double.isFinite(weight) || weight < 0 || weight > 1) {
			throw new IllegalArgumentException("w must be in the range [0, 1]");
		}
		this.taskLength = taskLength.clone();
		this.vmCapacity = vmCapacity.clone();
		this.energyModel = energyModel;
		this.weight = weight;

		double totalLength = 0;
		for (double length : this.taskLength) {
			totalLength += length;
		}
		double totalCapacity = 0;
		for (double capacity : this.vmCapacity) {
			totalCapacity += capacity;
		}
		makespanLowerBound = totalLength / totalCapacity;
		energyLowerBound = makespanLowerBound * energyModel.idleWatts()
				+ energyModel.minJoulePerMi() * totalLength;
	}

	/** F(x); every call counts as one evaluation of the budget. */
	public double evaluate(int[] mapping) {
		evaluations++;
		double makespan = makespan(mapping);
		double energy = energy(mapping, makespan);
		return weight * (makespan / makespanLowerBound) + (1.0 - weight) * (energy / energyLowerBound);
	}

	/** Cmax(x) in seconds. Does not count as an evaluation. */
	public double makespan(int[] mapping) {
		double[] loads = vmLoads(mapping);
		double max = loads[0];
		for (int vm = 1; vm < loads.length; vm++) {
			if (loads[vm] > max) {
				max = loads[vm];
			}
		}
		return max;
	}

	/** E(x) in Joules. Does not count as an evaluation. */
	public double energyJoules(int[] mapping) {
		return energy(mapping, makespan(mapping));
	}

	/** Sum of ETC per VM: loads[j] = sum_{i : x_i = j} L_i / C_j. */
	public double[] vmLoads(int[] mapping) {
		validate(mapping);
		double[] loads = new double[vmCapacity.length];
		for (int task = 0; task < mapping.length; task++) {
			int vm = mapping[task];
			loads[vm] += taskLength[task] / vmCapacity[vm];
		}
		return loads;
	}

	private double energy(int[] mapping, double makespan) {
		double dynamic = 0;
		for (int task = 0; task < mapping.length; task++) {
			dynamic += energyModel.joulePerMi(mapping[task]) * taskLength[task];
		}
		return makespan * energyModel.idleWatts() + dynamic;
	}

	private void validate(int[] mapping) {
		if (mapping == null || mapping.length != taskLength.length) {
			throw new IllegalArgumentException("Mapping must contain one VM for every task");
		}
		for (int vm : mapping) {
			if (vm < 0 || vm >= vmCapacity.length) {
				throw new IllegalArgumentException("Mapping contains an invalid VM index");
			}
		}
	}

	public long evaluations() { return evaluations; }
	public double weight() { return weight; }
	public double makespanLowerBound() { return makespanLowerBound; }
	public double energyLowerBound() { return energyLowerBound; }
	public int taskCount() { return taskLength.length; }
	public int vmCount() { return vmCapacity.length; }
}
