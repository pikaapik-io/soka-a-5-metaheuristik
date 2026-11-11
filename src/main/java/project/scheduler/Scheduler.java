package project.scheduler;

/** Assigns tasks to virtual machines using only scheduler-level data. */
public interface Scheduler {

	String getName();

	/**
	 * @param taskLength taskLength[i] is the length of task i in MI
	 * @param vmCapacity vmCapacity[j] is the capacity of VM j in MIPS
	 * @return mapping[i] is the VM index assigned to task i
	 */
	int[] schedule(double[] taskLength, double[] vmCapacity);
}
