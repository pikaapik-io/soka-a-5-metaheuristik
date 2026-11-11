package project.model;

/**
 * Analytic energy model of design section 3.2 (objective f2), independent of CloudSim.
 *
 * Every host is powered from 0 to Cmax, so the idle part is Cmax x sum P_idle. A task of
 * L MI keeps its host busy for L / (PE_host x MIPS_host) seconds, so the dynamic part is
 * kappa_j x L with kappa_j = (P_max - P_idle) / (PE_host x MIPS_host) of the host type
 * that VM j is placed on.
 */
public final class EnergyModel {
	private final double idleWatts;
	private final double[] joulePerMi;

	/**
	 * @param idleWatts  sum of P_idle over every host (741 W in the design)
	 * @param joulePerMi joulePerMi[j] is kappa of VM j in J/MI
	 */
	public EnergyModel(double idleWatts, double[] joulePerMi) {
		if (!Double.isFinite(idleWatts) || idleWatts < 0) {
			throw new IllegalArgumentException("Idle power must be finite and non-negative");
		}
		if (joulePerMi == null || joulePerMi.length == 0) {
			throw new IllegalArgumentException("kappa is required for every VM");
		}
		for (double kappa : joulePerMi) {
			if (!Double.isFinite(kappa) || kappa < 0) {
				throw new IllegalArgumentException("kappa must be finite and non-negative");
			}
		}
		this.idleWatts = idleWatts;
		this.joulePerMi = joulePerMi.clone();
	}

	/** kappa of a host type: (P_max - P_idle) / (PE x MIPS per PE). */
	public static double kappa(double maxPower, double idlePower, int pes, double mipsPerPe) {
		return (maxPower - idlePower) / (pes * mipsPerPe);
	}

	public double idleWatts() { return idleWatts; }
	public double joulePerMi(int vm) { return joulePerMi[vm]; }
	public int vmCount() { return joulePerMi.length; }

	/** Smallest kappa over all VMs, used by the energy lower bound E_LB. */
	public double minJoulePerMi() {
		double min = joulePerMi[0];
		for (int vm = 1; vm < joulePerMi.length; vm++) {
			if (joulePerMi[vm] < min) {
				min = joulePerMi[vm];
			}
		}
		return min;
	}
}
