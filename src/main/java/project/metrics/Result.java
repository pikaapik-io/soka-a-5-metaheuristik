package project.metrics;

/** The eight metrics of design section 4.1 for one simulation run. */
public final class Result {
	private final String scheduler;
	private final int tasks;
	private final double makespan;
	private final double energyKwh;
	private final double averageResponse;
	private final double utilizationPercent;
	private final double degreeOfImbalance;
	private final double degreeOfImbalanceUsedVms;
	private final double throughput;
	private final double totalCost;
	private final double schedulingMillis;
	private final double[] vmFinishTimes;

	public Result(String scheduler, int tasks, double makespan, double energyKwh,
				  double averageResponse, double utilizationPercent, double degreeOfImbalance,
				  double degreeOfImbalanceUsedVms, double throughput, double totalCost,
				  double schedulingMillis, double[] vmFinishTimes) {
		this.scheduler = scheduler;
		this.tasks = tasks;
		this.makespan = makespan;
		this.energyKwh = energyKwh;
		this.averageResponse = averageResponse;
		this.utilizationPercent = utilizationPercent;
		this.degreeOfImbalance = degreeOfImbalance;
		this.degreeOfImbalanceUsedVms = degreeOfImbalanceUsedVms;
		this.throughput = throughput;
		this.totalCost = totalCost;
		this.schedulingMillis = schedulingMillis;
		this.vmFinishTimes = vmFinishTimes.clone();
	}

	public String scheduler() { return scheduler; }
	public int tasks() { return tasks; }
	public double makespan() { return makespan; }
	public double energyKwh() { return energyKwh; }
	public double averageResponse() { return averageResponse; }
	public double utilizationPercent() { return utilizationPercent; }
	public double degreeOfImbalance() { return degreeOfImbalance; }
	public double degreeOfImbalanceUsedVms() { return degreeOfImbalanceUsedVms; }
	public double throughput() { return throughput; }
	public double totalCost() { return totalCost; }
	public double schedulingMillis() { return schedulingMillis; }
	public double[] vmFinishTimes() { return vmFinishTimes.clone(); }
}
