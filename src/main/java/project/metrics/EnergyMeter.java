package project.metrics;

import java.util.List;
import org.cloudbus.cloudsim.core.CloudSim;
import org.cloudbus.cloudsim.hosts.Host;
import project.setup.DatacenterFactory;
import project.setup.DatacenterFactory.HostType;

/**
 * Integrates host power over simulation time (design section 3.2):
 * E = sum_k integral [P_idle + (P_max - P_idle) * u_k(t)] dt, t from 0 to Cmax.
 *
 * PowerModelHostSimple only gives instantaneous power, so utilization is
 * sampled on every clock tick and integrated here (design risk 2). Every host
 * is counted for the whole run, including idle ones.
 */
public final class EnergyMeter {
	private final List<Host> hosts;
	private final double[] joules;
	private final double[] utilizationSeconds;
	private final double[] lastUtilization;
	private double lastTime;

	public EnergyMeter(CloudSim simulation, List<Host> hosts) {
		this.hosts = hosts;
		this.joules = new double[hosts.size()];
		this.utilizationSeconds = new double[hosts.size()];
		this.lastUtilization = new double[hosts.size()];
		simulation.addOnClockTickListener(info -> sample(info.getTime()));
	}

	private void sample(double now) {
		double dt = now - lastTime;
		for (int k = 0; k < hosts.size(); k++) {
			if (dt > 0) {
				utilizationSeconds[k] += lastUtilization[k] * dt;
			}
			lastUtilization[k] = hosts.get(k).getCpuPercentUtilization();
		}
		lastTime = Math.max(lastTime, now);
	}

	/** Energy of every host from 0 to makespan, in Joules. */
	public double[] hostJoules(double makespan) {
		for (int k = 0; k < hosts.size(); k++) {
			HostType type = DatacenterFactory.typeOf(hosts.get(k));
			joules[k] = type.idlePower * makespan
					+ (type.maxPower - type.idlePower) * utilizationSeconds[k];
		}
		return joules.clone();
	}

	/** integral u_k(t) dt for every host (seconds at 100% utilization). */
	public double[] utilizationSeconds() {
		return utilizationSeconds.clone();
	}

	public static double toKwh(double joules) {
		return joules / 3_600_000;
	}
}
