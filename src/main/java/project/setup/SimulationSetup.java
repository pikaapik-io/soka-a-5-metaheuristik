package project.setup;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.cloudbus.cloudsim.brokers.DatacenterBroker;
import org.cloudbus.cloudsim.brokers.DatacenterBrokerSimple;
import org.cloudbus.cloudsim.cloudlets.Cloudlet;
import org.cloudbus.cloudsim.cloudlets.CloudletSimple;
import org.cloudbus.cloudsim.core.CloudSim;
import org.cloudbus.cloudsim.datacenters.Datacenter;
import org.cloudbus.cloudsim.hosts.Host;
import org.cloudbus.cloudsim.utilizationmodels.UtilizationModelDynamic;
import org.cloudbus.cloudsim.utilizationmodels.UtilizationModelFull;
import org.cloudbus.cloudsim.vms.Vm;
import project.metrics.EnergyMeter;


public final class SimulationSetup {

	/** Cloudlet file and output size (KB), design section 1.3. */
	private static final long FILE_SIZE = 300;
	private static final long OUTPUT_SIZE = 300;
	private static final double RAM_BW_UTILIZATION = 0.2;

	private final CloudSim simulation;
	private final List<Datacenter> datacenters;
	private final DatacenterBroker broker;
	private final List<Vm> vmList;
	private final double[] taskLengths;
	private List<Cloudlet> cloudlets = new ArrayList<>();
	private final List<Host> hosts = new ArrayList<>();
	private final EnergyMeter energyMeter;
	private int[] mappingUsed;

	public SimulationSetup(double[] taskLengths) {
		simulation = new CloudSim();
		datacenters = DatacenterFactory.createAll(simulation);
		datacenters.forEach(dc -> hosts.addAll(dc.getHostList()));
		broker = new DatacenterBrokerSimple(simulation);
		// Keep every VM alive until the batch ends so idle VMs are billed too.
		broker.setVmDestructionDelay(Double.MAX_VALUE);
		vmList = VmFactory.createDefaultVms();
		this.taskLengths = taskLengths.clone();
		energyMeter = new EnergyMeter(simulation, hosts);
	}

	private List<Cloudlet> createCloudlets(int[] mapping) {
		List<Cloudlet> list = new ArrayList<>();
		for (int i = 0; i < taskLengths.length; i++) {
			int pes = (int) vmList.get(mapping[i]).getNumberOfPes();
			long lengthPerPe = Math.round(taskLengths[i] / pes);
			Cloudlet cloudlet = new CloudletSimple(i, lengthPerPe, pes)
					.setFileSize(FILE_SIZE)
					.setOutputSize(OUTPUT_SIZE)
					.setUtilizationModelCpu(new UtilizationModelFull())
					.setUtilizationModelRam(new UtilizationModelDynamic(RAM_BW_UTILIZATION))
					.setUtilizationModelBw(new UtilizationModelDynamic(RAM_BW_UTILIZATION));
			list.add(cloudlet);
		}
		return list;
	}

	/** Binds cloudlet i to VM mapping[i], runs the simulation and validates VM creation. */
	public void run(int[] mapping) {
		if (mapping.length != taskLengths.length) {
			throw new IllegalArgumentException("Mapping must contain one VM for every cloudlet");
		}
		cloudlets = createCloudlets(mapping);
		mappingUsed = mapping.clone();
		Map<Vm, Datacenter> plan = ConstrainedPlacement.planDatacenters(datacenters, vmList);
		broker.setDatacenterMapper((lastDc, vm) -> plan.get(vm));
		broker.submitVmList(vmList);
		broker.submitCloudletList(cloudlets);
		// Binding is silently ignored (returns false) before the cloudlet belongs to
		// the broker, so it must happen after submission and be checked.
		for (int i = 0; i < mapping.length; i++) {
			if (!broker.bindCloudletToVm(cloudlets.get(i), vmList.get(mapping[i]))) {
				throw new IllegalStateException("Cloudlet " + i + " could not be bound to VM " + mapping[i]);
			}
		}
		simulation.start();
		validate();
	}

	/** Design risk 3: VM allocation failures are silent, so check them explicitly. */
	private void validate() {
		int created = broker.getVmCreatedList().size();
		if (created != vmList.size()) {
			throw new IllegalStateException("Only " + created + " of " + vmList.size()
					+ " VMs were created; check host capacity and MIPS compatibility");
		}
		for (int i = 0; i < cloudlets.size(); i++) {
			if (cloudlets.get(i).getVm() != vmList.get(mappingUsed[i])) {
				throw new IllegalStateException("Cloudlet " + i + " ran on a different VM than scheduled");
			}
		}
		long finished = cloudlets.stream().filter(Cloudlet::isFinished).count();
		if (finished != cloudlets.size()) {
			throw new IllegalStateException("Only " + finished + " of " + cloudlets.size()
					+ " cloudlets finished");
		}
	}

	public CloudSim simulation() { return simulation; }
	public List<Datacenter> datacenters() { return datacenters; }
	public List<Host> hosts() { return hosts; }
	public DatacenterBroker broker() { return broker; }
	public List<Vm> vmList() { return vmList; }
	public List<Cloudlet> cloudlets() { return cloudlets; }
	public EnergyMeter energyMeter() { return energyMeter; }
}
