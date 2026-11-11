package project.setup;

import java.util.ArrayList;
import java.util.List;
import org.cloudbus.cloudsim.schedulers.cloudlet.CloudletSchedulerSpaceShared;
import org.cloudbus.cloudsim.vms.Vm;
import org.cloudbus.cloudsim.vms.VmSimple;

/**
 * 20 VMs from the project design (section 2.4). Index order is fixed:
 * VM 0-3 = V3 Large, VM 4-11 = V2 Medium, VM 12-19 = V1 Small.
 */
// total 20 VM dan rinciannya (jumlah, PE, MIPS, RAM per tipe) didefinisikan.
public final class VmFactory {

	/** VM type: count, PE count, MIPS per PE, RAM (MB), BW (Mbps). */
	public enum VmType {
		//  V3 Large, 4 VM (indeks 0-3), 4 PE x 2.500 MIPS, 8 GB RAM.
		// Batasan keras: MIPS/PE (2.500) > MIPS/PE host Tipe B (1.800), jadi hanya muat di DC-1 (lihat ConstrainedPlacement, C6).
		V3_LARGE(4, 4, 2_500, 8_192, 1_000),
		//  V2 Medium, 8 VM (indeks 4-11), 2 PE x 1.500 MIPS, 4 GB RAM. Muat di host Tipe A maupun B.
		V2_MEDIUM(8, 2, 1_500, 4_096, 1_000),
		//  V1 Small, 8 VM (indeks 12-19), 1 PE x 1.000 MIPS, 2 GB RAM. Muat di host Tipe A maupun B.
		V1_SMALL(8, 1, 1_000, 2_048, 500);

		public final int count;
		public final int pes;
		public final double mipsPerPe;
		public final long ram;
		public final long bw;

		VmType(int count, int pes, double mipsPerPe, long ram, long bw) {
			this.count = count;
			this.pes = pes;
			this.mipsPerPe = mipsPerPe;
			this.ram = ram;
			this.bw = bw;
		}

		public String label() { return name().substring(0, 2); }
	}

	/** VM image size (MB). Not specified in the design. */
	private static final long VM_SIZE = 10_000;

	private VmFactory() { }

	// total 20 VM = 4 V3 + 8 V2 + 8 V1, dibuat berurutan sesuai VmType.values().
	public static List<Vm> createDefaultVms() {
		List<Vm> vms = new ArrayList<>();
		for (VmType type : VmType.values()) {
			for (int i = 0; i < type.count; i++) {
				Vm vm = new VmSimple(vms.size(), type.mipsPerPe, type.pes);
				vm.setRam(type.ram).setBw(type.bw).setSize(VM_SIZE)
						.setCloudletScheduler(new CloudletSchedulerSpaceShared())
						.setDescription(type.label());
				vms.add(vm);
			}
		}
		return vms;
	}
}
