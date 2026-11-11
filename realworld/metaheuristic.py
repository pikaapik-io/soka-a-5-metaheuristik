#!/usr/bin/env python3
"""Port Python bit-identik dari HS dan CSA (src/main/java/project/scheduler/).

Real world harus menjalankan mapping yang SAMA dengan CloudSim untuk seed yang sama,
jadi setiap langkah di sini meniru kode Java baris per baris:

  * JavaRandom meniru java.util.Random (LCG 48-bit, multiplier 0x5DEECE66D). Algoritma
    hanya memakai next_int(bound) dan next_double(), termasuk rejection loop next_int.
  * Urutan pemanggilan RNG dan urutan operasi floating point sama dengan Java. Tidak ada
    exp, pow, log, atau sum() bawaan (Python 3.12 memakai penjumlahan terkompensasi).
  * Java mengevaluasi a[idx()] = f() dari indeks dulu, Python dari ruas kanan dulu. Jadi
    di Python ditulis dua baris: g = rng.next_int(n) lalu clone[g] = random_vm().
  * Pengurutan CSA stabil dengan kunci (affinity, indeks), sama dengan comparator Java.

Hanya standard library.
"""

MULTIPLIER = 0x5DEECE66D
ADDEND = 0xB
MASK = (1 << 48) - 1
DOUBLE_UNIT = 1.0 / (1 << 53)  # 0x1.0p-53, pangkat dua sehingga eksak

DEFAULT_BUDGET = 10_000
DEFAULT_WEIGHT = 0.5

# Parameter default, sama dengan konstanta DEFAULT_* di kelas Java.
HS_HMS = 20
HS_HMCR = 0.98
HS_PAR = 0.5
CSA_POPULATION = 20
CSA_SELECTED = 10
CSA_CLONE_FACTOR = 1.0
CSA_REPLACED = 2


class JavaRandom:
    """java.util.Random: setSeed, next(bits), nextInt(bound), nextDouble()."""

    def __init__(self, seed):
        self.seed = (seed ^ MULTIPLIER) & MASK

    def next(self, bits):
        self.seed = (self.seed * MULTIPLIER + ADDEND) & MASK
        value = self.seed >> (48 - bits)
        return value - (1 << 32) if value >= (1 << 31) else value  # cast ke int 32-bit

    def next_int(self, bound):
        if bound <= 0:
            raise ValueError("bound must be positive")
        r = self.next(31)
        m = bound - 1
        if bound & m == 0:  # pangkat dua
            return (bound * r) >> 31
        u = r
        r = u % bound
        while u - r + m >= (1 << 31):  # di Java: overflow int -> negatif -> tolak
            u = self.next(31)
            r = u % bound
        return r

    def next_double(self):
        high = self.next(26)
        low = self.next(27)
        return ((high << 27) + low) * DOUBLE_UNIT


class EnergyModel:
    """Sama dengan project.model.EnergyModel: sum P_idle dan kappa (J/MI) per VM."""

    def __init__(self, idle_watts, joule_per_mi):
        self.idle_watts = idle_watts
        self.joule_per_mi = list(joule_per_mi)

    @staticmethod
    def kappa(p_max, p_idle, pes, mips_per_pe):
        return (p_max - p_idle) / (pes * mips_per_pe)

    def min_joule_per_mi(self):
        best = self.joule_per_mi[0]
        for k in self.joule_per_mi[1:]:
            if k < best:
                best = k
        return best


class Objective:
    """Sama dengan project.model.ObjectiveFunction: F(x) = w*Cmax/C_LB + (1-w)*E/E_LB."""

    def __init__(self, lengths, capacities, energy_model, weight):
        if not 0 <= weight <= 1:
            raise ValueError("w must be in the range [0, 1]")
        self.lengths = [float(x) for x in lengths]
        self.capacities = [float(c) for c in capacities]
        self.energy_model = energy_model
        self.weight = weight
        self.evaluations = 0

        total_length = 0.0
        for length in self.lengths:
            total_length += length
        total_capacity = 0.0
        for capacity in self.capacities:
            total_capacity += capacity
        self.makespan_lb = total_length / total_capacity
        self.energy_lb = (self.makespan_lb * energy_model.idle_watts
                          + energy_model.min_joule_per_mi() * total_length)

        # ETC dan kappa*L per (task, VM) dihitung sekali; nilainya sama persis dengan
        # pembagian/perkalian yang dilakukan Java di setiap evaluasi.
        self._etc = [[length / c for c in self.capacities] for length in self.lengths]
        self._dyn = [[k * length for k in energy_model.joule_per_mi] for length in self.lengths]

    def _loads_and_dynamic(self, mapping):
        loads = [0.0] * len(self.capacities)
        dynamic = 0.0
        etc, dyn = self._etc, self._dyn
        for task, vm in enumerate(mapping):
            loads[vm] += etc[task][vm]
            dynamic += dyn[task][vm]
        return loads, dynamic

    def evaluate(self, mapping):
        self.evaluations += 1
        loads, dynamic = self._loads_and_dynamic(mapping)
        makespan = max(loads)
        energy = makespan * self.energy_model.idle_watts + dynamic
        return self.weight * (makespan / self.makespan_lb) + (1.0 - self.weight) * (energy / self.energy_lb)

    def makespan(self, mapping):
        """Cmax(x) dalam detik simulasi; tidak menambah hitungan evaluasi."""
        return max(self._loads_and_dynamic(mapping)[0])

    def energy_joules(self, mapping):
        """E(x) dalam Joule; tidak menambah hitungan evaluasi."""
        loads, dynamic = self._loads_and_dynamic(mapping)
        return max(loads) * self.energy_model.idle_watts + dynamic


class MetaheuristicScheduler:
    """Sama dengan MetaheuristicScheduler.java: seed, w, budget, randomVm, trace."""

    name = "?"

    def __init__(self, energy_model, seed, weight=DEFAULT_WEIGHT, max_evaluations=DEFAULT_BUDGET):
        if max_evaluations < 1:
            raise ValueError("The evaluation budget must be positive")
        self.energy_model = energy_model
        self.seed = seed
        self.weight = weight
        self.max_evaluations = max_evaluations
        self.objective = None
        self.rng = None
        self.trace = []
        self.best_fitness = float("inf")

    def schedule(self, lengths, capacities):
        if not lengths or not capacities:
            raise ValueError("At least one task and one VM are required")
        self.objective = Objective(lengths, capacities, self.energy_model, self.weight)
        self.rng = JavaRandom(self.seed)
        total = 0.0
        for c in capacities:
            total += float(c)
        self._cumulative = []
        prefix = 0.0
        for c in capacities:
            prefix += float(c)
            self._cumulative.append(prefix / total)
        self.trace = []
        self.best_fitness = float("inf")
        return list(self.search(len(lengths)))

    def search(self, task_count):
        raise NotImplementedError

    @property
    def evaluations_used(self):
        return self.objective.evaluations

    def budget_left(self):
        return self.objective.evaluations < self.max_evaluations

    def evaluate(self, mapping):
        if not self.budget_left():
            raise RuntimeError("Evaluation budget exhausted")
        fitness = self.objective.evaluate(mapping)
        if fitness < self.best_fitness:
            self.best_fitness = fitness
        self.trace.append(self.best_fitness)
        return fitness

    def random_vm(self):
        r = self.rng.next_double()
        for vm, share in enumerate(self._cumulative):
            if r < share:
                return vm
        return len(self._cumulative) - 1

    def random_solution(self, task_count):
        return [self.random_vm() for _ in range(task_count)]


def arg_min(values):
    best = 0
    for k in range(1, len(values)):
        if values[k] < values[best]:
            best = k
    return best


def arg_max(values):
    worst = 0
    for k in range(1, len(values)):
        if values[k] > values[worst]:
            worst = k
    return worst


class HarmonySearch(MetaheuristicScheduler):
    """Port HarmonySearchScheduler.java (Global-best HS, satu iterasi = satu evaluasi)."""

    name = "HS"

    def __init__(self, energy_model, seed, weight=DEFAULT_WEIGHT, max_evaluations=DEFAULT_BUDGET,
                 hms=HS_HMS, hmcr=HS_HMCR, par=HS_PAR):
        super().__init__(energy_model, seed, weight, max_evaluations)
        if hms < 2 or hms > max_evaluations:
            raise ValueError("HMS must be in the range [2, budget]")
        self.hms, self.hmcr, self.par = hms, hmcr, par

    def search(self, task_count):
        hms, hmcr, par = self.hms, self.hmcr, self.par
        memory, fitness = [], []
        for _ in range(hms):
            harmony = self.random_solution(task_count)
            memory.append(harmony)
            fitness.append(self.evaluate(harmony))

        rng = self.rng
        next_double, next_int, random_vm = rng.next_double, rng.next_int, self.random_vm
        for _ in range(hms, self.max_evaluations):
            best = memory[arg_min(fitness)]
            harmony = [0] * task_count
            for task in range(task_count):
                if next_double() < hmcr:
                    vm = memory[next_int(hms)][task]
                    if next_double() < par:
                        vm = best[task]
                else:
                    vm = random_vm()
                harmony[task] = vm
            new_fitness = self.evaluate(harmony)
            worst = arg_max(fitness)
            if new_fitness < fitness[worst]:
                memory[worst] = harmony
                fitness[worst] = new_fitness
        return memory[arg_min(fitness)]


class ClonalSelection(MetaheuristicScheduler):
    """Port ClonalSelectionScheduler.java (CLONALG, mutasi linear per ranking)."""

    name = "CSA"

    def __init__(self, energy_model, seed, weight=DEFAULT_WEIGHT, max_evaluations=DEFAULT_BUDGET,
                 population=CSA_POPULATION, selected=CSA_SELECTED, clone_factor=CSA_CLONE_FACTOR,
                 replaced=CSA_REPLACED):
        super().__init__(energy_model, seed, weight, max_evaluations)
        if population < 2 or population > max_evaluations:
            raise ValueError("N must be in the range [2, budget]")
        if selected < 1 or replaced < 0 or selected + replaced > population:
            raise ValueError("Need 1 <= n and n + d <= N")
        self.population, self.selected = population, selected
        self.clone_factor, self.replaced = clone_factor, replaced

    @staticmethod
    def max_mutation(task_count):
        return max(1, task_count // 20)

    def clone_count(self, rank):
        return max(1, int(self.clone_factor * self.population / (rank + 1)))

    def mutation_count(self, rank, max_mutation):
        return 1 + rank * (max_mutation - 1) // max(1, self.selected - 1)

    def search(self, task_count):
        n_pop, max_mutation = self.population, self.max_mutation(task_count)
        population, affinity = [], []
        for _ in range(n_pop):
            antibody = self.random_solution(task_count)
            population.append(antibody)
            affinity.append(self.evaluate(antibody))

        rng = self.rng
        while self.budget_left():
            order = sorted(range(n_pop), key=lambda k: (affinity[k], k))
            population = [population[k] for k in order]
            affinity = [affinity[k] for k in order]

            rank = 0
            while rank < self.selected and self.budget_left():
                clones = self.clone_count(rank)
                mutations = self.mutation_count(rank, max_mutation)
                best_clone, best_affinity = None, affinity[rank]
                c = 0
                while c < clones and self.budget_left():
                    clone = population[rank][:]
                    for _ in range(mutations):
                        gene = rng.next_int(task_count)  # indeks dulu, seperti Java
                        clone[gene] = self.random_vm()
                    clone_affinity = self.evaluate(clone)
                    if clone_affinity < best_affinity:
                        best_affinity, best_clone = clone_affinity, clone
                    c += 1
                if best_clone is not None:
                    population[rank], affinity[rank] = best_clone, best_affinity
                rank += 1

            k = n_pop - self.replaced
            while k < n_pop and self.budget_left():
                population[k] = self.random_solution(task_count)
                affinity[k] = self.evaluate(population[k])
                k += 1
        return population[arg_min(affinity)]


ALGORITHMS = {"HS": HarmonySearch, "CSA": ClonalSelection}


def create(algorithm, energy_model, seed, weight=DEFAULT_WEIGHT, budget=DEFAULT_BUDGET):
    try:
        return ALGORITHMS[algorithm.upper()](energy_model, seed, weight, budget)
    except KeyError:
        raise ValueError(f"Algorithm must be HS or CSA, got {algorithm}") from None
