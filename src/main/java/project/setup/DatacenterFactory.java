package project.setup;

import java.util.ArrayList;
import java.util.List;
import org.cloudbus.cloudsim.allocationpolicies.VmAllocationPolicySimple;
import org.cloudbus.cloudsim.core.CloudSim;
import org.cloudbus.cloudsim.datacenters.Datacenter;
import org.cloudbus.cloudsim.datacenters.DatacenterSimple;
import org.cloudbus.cloudsim.hosts.Host;
import org.cloudbus.cloudsim.hosts.HostSimple;
import org.cloudbus.cloudsim.power.models.PowerModelHostSimple;
import org.cloudbus.cloudsim.resources.Pe;
import org.cloudbus.cloudsim.resources.PeSimple;
import org.cloudbus.cloudsim.schedulers.vm.VmSchedulerTimeShared;

/**
 * Two datacenters from the project design (section 2.2-2.3):
 * DC-1 Performance with 3 Type A hosts and DC-2 Efficiency with 3 Type B hosts.
 */
public final class DatacenterFactory {

	/** Host type: PE count, MIPS per PE, RAM (MB), BW (Mbps), storage (MB), power (W). */
	public enum HostType {
		// ★ TUNJUK: Host Tipe A (DC-1 Performance), 8 PE x 3.000 MIPS, 32 GB RAM, 10 Gbps, P idle 175 W / P max 250 W.
		A_PERFORMANCE(8, 3_000, 32_768, 10_000, 1_000_000, 250, 175),
		// ★ TUNJUK: Host Tipe B (DC-2 Efficiency), 8 PE x 1.800 MIPS, 32 GB RAM, 5 Gbps, P idle 72 W / P max 120 W.
		B_EFFICIENCY(8, 1_800, 32_768, 5_000, 1_000_000, 120, 72);

		public final int pes;
		public final double mipsPerPe;
		public final long ram;
		public final long bw;
		public final long storage;
		public final double maxPower;
		public final double idlePower;

		HostType(int pes, double mipsPerPe, long ram, long bw, long storage,
				 double maxPower, double idlePower) {
			this.pes = pes;
			this.mipsPerPe = mipsPerPe;
			this.ram = ram;
			this.bw = bw;
			this.storage = storage;
			this.maxPower = maxPower;
			this.idlePower = idlePower;
		}

		public double totalMips() { return pes * mipsPerPe; }
	}

	/** Scheduling interval  */
	public static final double SCHEDULING_INTERVAL = 1.0;

	// ★ TUNJUK: 3 host per DC -> total 2 DC x 3 host = 6 host (48 PE, 192 GB RAM di seluruh sistem).
	private static final int HOSTS_PER_DATACENTER = 3;
	private static final double MB_PER_GB = 1024.0;

	private DatacenterFactory() { }

	// ★ TUNJUK: di sinilah 2 datacenter dibuat - DC-1 Performance (host Tipe A) dan DC-2 Efficiency (host Tipe B).
	/** @return [DC-1 Performance, DC-2 Efficiency] */
	public static List<Datacenter> createAll(CloudSim simulation) {
		List<Datacenter> datacenters = new ArrayList<>();
		datacenters.add(create(simulation, HostType.A_PERFORMANCE, 0.05, 0.02, 0.001, 0.005));
		datacenters.add(create(simulation, HostType.B_EFFICIENCY, 0.03, 0.01, 0.0008, 0.003));
		return datacenters;
	}

	/**
	 * Costs follow design table per second, per GB RAM, per GB storage, per
	 * Mbps bandwidth. CloudSim expects RAM and storage costs per MB.
	 */
	private static Datacenter create(CloudSim simulation, HostType type, double costPerSecond,
									 double costPerGbRam, double costPerGbStorage, double costPerBw) {
		List<Host> hosts = new ArrayList<>();
		for (int i = 0; i < HOSTS_PER_DATACENTER; i++) {
			hosts.add(createHost(type));
		}
		DatacenterSimple datacenter = new DatacenterSimple(simulation, hosts,
				new VmAllocationPolicySimple(ConstrainedPlacement::findHost));
		datacenter.setSchedulingInterval(SCHEDULING_INTERVAL);
		datacenter.getCharacteristics()
				.setArchitecture("x86")
				.setOs("Linux")
				.setVmm("Xen")
				.setCostPerSecond(costPerSecond)
				.setCostPerMem(costPerGbRam / MB_PER_GB)
				.setCostPerStorage(costPerGbStorage / MB_PER_GB)
				.setCostPerBw(costPerBw);
		return datacenter;
	}

	private static Host createHost(HostType type) {
		List<Pe> pes = new ArrayList<>();
		for (int pe = 0; pe < type.pes; pe++) {
			pes.add(new PeSimple(type.mipsPerPe));
		}
		HostSimple host = new HostSimple(type.ram, type.bw, type.storage, pes);
		host.setVmScheduler(new VmSchedulerTimeShared());
		// Linear model P(u) = P_idle + (P_max - P_idle) * u
		host.setPowerModel(new PowerModelHostSimple(type.maxPower, type.idlePower));
		return host;
	}

	/** Host type is identified from the MIPS per PE of the host. */
	public static HostType typeOf(Host host) {
		return host.getMips() == HostType.A_PERFORMANCE.mipsPerPe
				? HostType.A_PERFORMANCE : HostType.B_EFFICIENCY;
	}
}
