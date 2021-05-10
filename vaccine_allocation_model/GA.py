import numpy as np
import scipy
from covid.utils import tcolors, write_pickle
import pandas as pd
import os
from datetime import datetime
from tqdm import tqdm
from collections import defaultdict
from functools import partial

class SimpleGeneticAlgorithm:
    def __init__(self, simulations, population_size, process, objective, verbose, random_individuals=False):
        """initializes a simple genetic algorithm instance

        Args:
            simulations (int): number specifying number of simulations
            population_size (int): number of individuals to initialize population with
            process (MarkovDecisionProcess): a process to simulate fitness of individuals
            objective (str): choice of metric to evaluate fitness
            verbose (bool): specify whether or not to print
        """
        self.simulations = simulations
        self.process = process
        self.population = Population(population_size, verbose, random_individuals)
        self.generation_count = 0
        self.final_scores = defaultdict(list)
        self.best_individual = None
        self.best_scores = np.inf
        self.generations_since_new_best = 0
        self.objective = self._set_objective(objective)
        self.number_of_runs = []
        self._generate_output_dirs()
        self.verbose = verbose

    def _generate_output_dirs(self):
            start_of_run = datetime.now().strftime("%Y_%m_%d_%H:%M:%S")
            run_folder = f"/results/GA_{start_of_run}"
            folder_path = os.getcwd()+run_folder
            individuals_path = folder_path + "/individuals"
            final_scores_path = folder_path + "/final_scores"
            os.mkdir(folder_path)
            os.mkdir(individuals_path)
            os.mkdir(final_scores_path)
            self.overview_path = folder_path + f"/generation_overview.csv"
            self.individuals_path = folder_path + f"/individuals/individuals_"
            self.final_score_path = folder_path + f"/final_scores/final_score_"

    def _set_objective(self, objective):
        return {"deaths": lambda process: np.sum(process.path[-1].D),
                "weighted": lambda process: np.sum(process.path[-1].total_infected)*0.01 + np.sum(process.path[-1].D),
                "yll": lambda process: np.sum(process.path[-1].yll)
                }[objective]

    def run(self):
        """function to evaluate current generation, create offsprings, evaluate offsprings, and generate new generations if not converged
        """
        while True:
            self.run_population()
            self.write_to_file()
            if self.check_convergence():
                break
            self.crossover(self.generation_count)
            self.mutation()
            self.repair_offsprings()
            self.run_population(offsprings=True)
            self.population.new_generation(self.generation_count)
            self.generation_count += 1

    def run_population(self, offsprings=False):
        """for current population, simulate

        Args:
            offsprings (bool, optional): if population to be run is offsprings of a generation. Defaults to False.

        Returns:
            bool: True if the two best scores of the population also is significant best
        """
        if self.verbose: print(f"\n\n{tcolors.OKBLUE}Running{' offsprings of ' if offsprings else ' '}generation {self.generation_count}{tcolors.ENDC}")
        self.find_fitness(offsprings)
        count = 0
        significant_best = self.find_best_individual(offsprings)
        while not significant_best and count <= 2:
            if self.verbose: print("Running more simulations...")
            self.find_fitness(offsprings, from_start=False)
            significant_best = self.find_best_individual(offsprings)
            count += 1
        self.find_runs(count)

        if self.verbose:
            if significant_best:
                print(f"{tcolors.OKGREEN}Significant best {'offspring' if offsprings else 'individual'} found{tcolors.ENDC}")
                if offsprings:
                    print(f"Best offspring of generation {self.generation_count}: {self.population.offsprings[0]}")
                else:
                    print(f"Best individual of generation {self.generation_count}: {self.population.individuals[0]}")
            else:
                print(f"{tcolors.FAIL}Significant best {'offspring' if offsprings else 'individual'} not found.")

        return significant_best

    def check_convergence(self):
        """checks if the best individual of the current population is better than the previous best

        Returns:
            bool: True if new all-time best individual is found
        """
        candidate = self.population.individuals[0]
        if self.generation_count == 0:
            self.best_individual = candidate
            self.best_scores = self.final_scores[candidate.ID]
        else:
            if candidate == self.best_individual:
                self.generations_since_new_best += 1
                if self.generations_since_new_best > 2:
                    print(f"{tcolors.OKGREEN}Converged. Best individual: {self.best_individual.ID}, score: {np.mean(self.best_scores)}{tcolors.ENDC}")
                    return True
                return False
            if self.verbose: print(f"Testing best of generation {self.generation_count} against all-time high")
            self.population.offsprings = [candidate, self.best_individual]
            self.find_fitness(offsprings=True)
            new_best = self.find_best_individual(offsprings=True)
            count = 0
            while not new_best and count < 3:
                new_best = self.find_fitness(offsprings=True, from_start=False)
                count += 1
            if new_best:
                self.best_individual = candidate
                self.best_scores = self.final_scores[candidate.ID]
                self.generations_since_new_best = 0
            else:
                self.generations_since_new_best += 1
                if self.generations_since_new_best > 2:
                    print(f"{tcolors.OKGREEN}Converged. Best individual: {self.best_individual.ID}, score: {np.mean(self.best_scores)}{tcolors.ENDC}")
                    return True
        return False

    def find_fitness(self, offsprings=False, from_start=True):
        """find estimated fitness of every individual through simulation of process

        Args:
            offsprings (bool, optional): if population to be run is offsprings of a generation. Defaults to False.
            from_start (bool, optional): if fitness is to be estimated from scratch. Defaults to True.
        """
        population = self.population.individuals if not offsprings else self.population.offsprings
        self.final_scores = defaultdict(list) if from_start else self.final_scores
        runs = self.simulations if from_start else int(self.simulations/2)
        seeds = [np.random.randint(0, 1e+6) for _ in range(runs)]
        for individual in population:
            if self.verbose: print(f"\nFinding score for individual {individual.ID}...")
            for j in tqdm(range(runs), ascii=True):
                np.random.seed(seeds[j])
                self.process.init()
                self.process.run(weighted_policy_weights=individual.genes)
                for wave_state, count in self.process.path[-1].strategy_count.items():
                    for wave_count, count in count.items():
                        individual.strategy_count[self.generation_count][wave_state][wave_count] += count
                score = self.objective(self.process)
                self.final_scores[individual.ID].append(score)
            mean_score = np.mean(self.final_scores[individual.ID])
            if self.verbose: print(f"Mean score: {mean_score:.0f}")
            individual.mean_score = mean_score

    def find_best_individual(self, offsprings=False):
        """loop through two most promising individuals to check for significance

        Args:
            offsprings (bool, optional): if population to be run is offsprings of a generation. Defaults to False.

        Returns:
            bool: True if both first and second best individuals passes t-test with significance
        """
        if self.verbose: print(f"\nFinding best individual...")
        self.population.sort_by_mean(offsprings)
        range1, range2 = (2, len(self.population.individuals)) if not offsprings else (1, len(self.population.offsprings))
        for i in range(range1): # test two best
            first = self.population.individuals[i] if not offsprings else self.population.offsprings[i]
            for j in range(i+1, range2):
                second = self.population.individuals[j] if not offsprings else self.population.offsprings[j]
                s1, s2 = self.final_scores[first.ID], self.final_scores[second.ID]
                if not self.t_test(s1, s2):
                    if self.verbose: print(f"{tcolors.WARNING}Significance not fulfilled between {first} and {second}.{tcolors.ENDC}")
                    return False
        return True

    def t_test(self, s1, s2, significance=0.1):
        """performs one-sided t-test to check to variables for significant difference

        Args:
            s1 (list): list of outcomes from simulations, from presumed best individual
            s2 (list): list of outcomes from simulations, from presumed worse individual
            significance (float, optional): level of significance to test against. Defaults to 0.1.

        Returns:
            bool: True if significance is achieved
        """
        significant_best = False
        s1 = np.array(s1)
        s2 = np.array(s2)
        if not (s1==s2).all():
            z = s1 - s2
            p = scipy.stats.ttest_ind(z, np.zeros(len(s1)), alternative="less").pvalue
            significant_best = p < significance
        return significant_best

    def crossover(self, generation_count):
        """creates offspring from two fittest individuals

        Args:
            generation_count (int): what generation that is creating offsprings
        """
        p1 = self.population.individuals[0].genes
        p2 = self.population.individuals[1].genes
        shape = p1.shape
        o1_genes = np.zeros(shape)
        o2_genes = np.zeros(shape)
        c_row = np.random.randint(0, high=shape[1])
        c_col = np.random.randint(0, high=shape[2])
        vertical_cross = np.random.random() <= 0.5
        if vertical_cross:
            o1_genes[:, :, :c_col] = p1[:, :, :c_col]
            o1_genes[:, :c_row, c_col] = p1[:, :c_row, c_col]
            o1_genes[:, c_row:, c_col] = p2[:, c_row:, c_col]
            o1_genes[:, :, c_col+1:] = p2[:, :, c_col+1:]
            o2_genes[:, :, :c_col] = p2[:, :, :c_col]
            o2_genes[:, :c_row, c_col] = p2[:, :c_row, c_col]
            o2_genes[:, c_row:, c_col] = p1[:, c_row:, c_col]
            o2_genes[:, :, c_col+1:] = p1[:, :, c_col+1:]
        else:
            o1_genes[:, :c_row, :] = p1[:, :c_row, :]
            o1_genes[:, c_row, :c_col] = p1[:, c_row, :c_col]
            o1_genes[:, c_row, c_col:] = p2[:, c_row, c_col:]
            o1_genes[:, c_row+1:, :] = p2[:, c_row+1:, :]
            o2_genes[:, :c_row, :] = p2[:, :c_row, :]
            o2_genes[:, c_row, :c_col] = p2[:, c_row, :c_col]
            o2_genes[:, c_row, c_col:] = p1[:, c_row, c_col:]
            o2_genes[:, c_row+1:, :] = p1[:, c_row+1:, :]
        o1 = Individual(generation=generation_count, offspring=True)
        o1.genes = o1_genes
        o2 = Individual(generation=generation_count, offspring=True)
        o2.genes = o2_genes
        o3 = Individual(generation=generation_count, offspring=True)
        o3.genes = np.divide(p1+p2, 2)
        o4 = Individual(generation=generation_count, offspring=True)
        o4.genes = np.divide(p1+3*p2, 4)
        o5 = Individual(generation=generation_count, offspring=True)
        o5.genes = np.divide(3*p1+p2, 4)
        self.population.offsprings = [o1,o2,o3,o4,o5]

    def mutation(self):
        """Randomly altering the genes of offsprings
        """
        for offspring in self.population.offsprings:
            shape = offspring.genes.shape
            draw = np.random.random() 
            while draw > 0.1:
                i1 = np.random.randint(0, high=shape[0])
                j1 = np.random.randint(0, high=shape[1])
                k1 = np.random.randint(0, high=shape[2])
                i2 = np.random.randint(0, high=shape[0])
                while i1 == i2: i2 = np.random.randint(0, high=shape[0])
                j2 = np.random.randint(0, high=shape[1])
                while j1 == j2: j2 = np.random.randint(0, high=shape[1])
                k2 = np.random.randint(0, high=shape[2])
                while k1 == k2: k2 = np.random.randint(0, high=shape[2])
                value = offspring.genes[i1, j1, k1]
                offspring.genes[i1, j1, k1] = offspring.genes[i2, j2, k2]
                offspring.genes[i2, j2, k2] = value
                draw = np.random.random()
    
    def repair_offsprings(self):
        """Make sure the genes of offsprings are feasible, i.e. normalize.
        """
        for offspring in self.population.offsprings:
            norm = np.sum(offspring.genes, axis=2, keepdims=True)
            for loc in np.argwhere(norm==0):
                i=loc[0]
                j=loc[1]
                offspring.genes[i,j,:] = np.array([1,0,0,0])
            norm = np.sum(offspring.genes, axis=2, keepdims=True)
            offspring.genes = np.divide(offspring.genes, norm)

    def find_runs(self, count):
        """Find number of runs needed before significance is needed.

        Args:
            count (int)): how many extra iterations needed to reach significant
        """
        number_runs = self.simulations
        if count > 0:
            for _ in range(count): number_runs += int(self.simulations/2)
        self.number_of_runs.append(number_runs)

    def write_to_file(self):
        """dump individuals and corresponding scores as pickle
        """
        write_pickle(self.individuals_path+str(self.generation_count)+".pkl", self.population.individuals)
        write_pickle(self.final_score_path+str(self.generation_count)+".pkl", self.final_scores)
        self.to_pandas()

    def to_pandas(self):
        """ Write summary of genetic algorithm run to csv
        """
        generation = [self.generation_count for _ in range(len(self.population.individuals))]
        ids = [individual.ID for individual in self.population.individuals]
        mean_score = [individual.mean_score for individual in self.population.individuals]
        gen_df = pd.DataFrame({"generation": generation, "individual": ids, "mean_score": mean_score})
        if self.generation_count == 0 :
            gen_df.to_csv(self.overview_path, header=True, index=False)
        else:
            gen_df.to_csv(self.overview_path, mode='a', header=False, index=False)

class Population: 
    def __init__(self, population_size, verbose, random_individuals):
        """create population object

        Args:
            population_size (int): number of individuals to initialize population with
            verbose (bool): specify whether or not to print
        """
        
        if random_individuals:
            self.individuals = [Individual() for _ in range(population_size)]
        else:
            self.individuals = [Individual(i) for i in range(population_size)]
        self.verbose = verbose
        self.least_fittest_index = 0
        self.offsprings = None
        if self.verbose: print(f"{tcolors.OKCYAN}Initial population: {self.individuals}{tcolors.ENDC}")
    
    def new_generation(self, generation_count):
        """create new generation 

        Args:
            generation_count (int): what number of population this is
        """
        if 10 < generation_count <= 20:
            self.individuals = self.individuals[:-2]
        elif generation_count > 20:
            self.individuals = self.individuals[:-1]
        self.individuals.append(self.offsprings[0])
        if self.verbose: print(f"{tcolors.OKCYAN}New generation: {self.individuals}{tcolors.ENDC}")
    
    def sort_by_mean(self, offsprings=False):
        """ sort individuals or offspring in ascending order

        Args:
            offsprings (bool, optional): True if offsprings are to be sorted. Defaults to False.
        """
        if not offsprings:
            self.individuals = sorted(self.individuals, key=lambda x: x.mean_score)
        else:
            self.offsprings = sorted(self.offsprings, key=lambda x: x.mean_score)    

class Individual:
    ID_COUNTER=1
    GENERATION=0

    def __init__(self, i=-1, generation=0, offspring=False):
        """create individual instance

        Args:
            i (int, optional): what number of individual it is, to determine genes. Defaults to -1.
            generation (int, optional): what generation the individual belongs to. Defaults to 0.
            offspring (bool, optional): True if the individual is an offspring. Defaults to False.
        """
        self.ID = self.get_id(generation, offspring)
        self.mean_score = 0
        self.genetype = i
        self.genes = self.create_genes(i)
        self.strategy_count = defaultdict(partial(defaultdict, partial(defaultdict, int)))
    
    def get_id(self, generation, offspring):
        """generate id of individual

        Args:
            generation (int): what generation the individual belongs to
            offspring (bool): True if the individual is an offspring. False otherwise

        Returns:
            str: id of individual
        """
        if offspring and generation == Individual.GENERATION: 
            Individual.GENERATION += 1
            Individual.ID_COUNTER = 1
        id = f"gen_{Individual.GENERATION}"
        id += f"_{Individual.ID_COUNTER:03d}"
        Individual.ID_COUNTER += 1
        return id

    def create_genes(self, i):
        """create genes for individual

        Args:
            i (int): number in order to assign different genes to different individuals

        Returns:
            numpy.ndarray: shape #wave_states, #times_per_state, #number of weights
        """
        genes = np.zeros((3,4,4))
        if 0 <= i < 4:
            genes[:,:,i] = 1
        elif 4 <= i < 7:
            j = (i+1)%4
            k = (i+3)%4 if i==6 else (i+2)%4
            genes[:, :, j] = 0.5
            genes[:, :, k] = 0.5
        elif i==7:
            genes[:, :, 1] = 0.33
            genes[:, :, 2] = 0.33
            genes[:, :, 3] = 0.34
        elif i==8:
            for j in range(4):
                genes[:, :, j] = 0.25
        elif 9 <= i < 10: # Set one weight vector randomly, make for each timestep
            weights = np.zeros(4)
            for j in range(4):
                high = 100 if j > 0 else 50
                weights[j] = np.random.randint(low=0, high=high) # nr wave_states, max nr of occurrences (wavecounts), nr of weights (policies)
            norm = np.sum(weights)
            genes[:, :] = np.divide(weights, norm)
        else:
            genes = np.random.randint(low=0, high=100, size=(3,4,4)) # nr wave_states, max nr of occurrences (wavecounts), nr of weights (policies)
            norm = np.sum(genes, axis=2, keepdims=True)
            genes = np.divide(genes, norm)
        return genes

    def __str__(self):
        return self.ID
    
    def __repr__(self):
        return self.ID