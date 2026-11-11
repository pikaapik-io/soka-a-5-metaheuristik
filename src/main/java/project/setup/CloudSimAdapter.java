package project.setup;

import java.util.List;
import java.util.Map;
import org.cloudbus.cloudsim.cloudlets.Cloudlet;
import org.cloudbus.cloudsim.datacenters.Datacenter;
import org.cloudbus.cloudsim.hosts.Host;
import org.cloudbus.cloudsim.vms.Vm;
import project.model.EnergyModel;
import project.setup.DatacenterFactory.HostType;

public final class CloudSimAdapter {
	private CloudSimAdapter() { }

	public static double[] taskLengths(List<? extends Cloudlet> cloudlets) {
		return cloudlets.stream().mapToDouble(Cloudlet::getTotalLength).toArray();
	}

	public static double[] vmCapacities(List<? extends Vm> vms) {
		return vms.stream().mapToDouble(vm -> vm.getMips() * vm.getNumberOfPes()).toArray();
	}

	/**
	 * Energy model for the scheduler: sum of P_idle over every host and kappa per VM, taken
	 * from the host type of the datacenter each VM is planned on. The plan is the same one
	 * SimulationSetup.run() uses, so it is known before the simulation starts.
	 */
	public static EnergyModel energyModel(SimulationSetup setup) {
		double idleWatts = 0;
		for (Host host : setup.hosts()) {
			idleWatts += DatacenterFactory.typeOf(host).idlePower;
		}
		Map<Vm, Datacenter> plan = ConstrainedPlacement.planDatacenters(setup.datacenters(), setup.vmList());
		double[] joulePerMi = new double[setup.vmList().size()];
		for (int vm = 0; vm < joulePerMi.length; vm++) {
			HostType type = DatacenterFactory.typeOf(plan.get(setup.vmList().get(vm)).getHost(0));
			joulePerMi[vm] = EnergyModel.kappa(type.maxPower, type.idlePower, type.pes, type.mipsPerPe);
		}
		return new EnergyModel(idleWatts, joulePerMi);
	}
}
