from vaccine_allocation_model.State import State
import numpy as np
from tqdm import tqdm
np.random.seed(10)

class MarkovDecisionProcess:
    def __init__(self, population, epidemic_function, initial_state, horizon, decision_period, policy, fhi_data=None, verbose=False):
        """ Initializes an instance of the class MarkovDecisionProcess, that administrates

        Parameters
            OD_matrices: Origin-Destination matrices giving movement patterns between regions
            population: A DataFrame with region_id, region_name and population
            epidemic_function: An epidemic model that enables simulation of the decision process
            vaccine_supply: Information about supply of vaccines, shape e.g. (#decision_period, #regions)
            horizon: The amount of decision_periods the decision process is run 
            decision_period: The number of time steps that every decision directly affects
            policy: How the available vaccines should be distributed.
            fhi_data: dataframe, or None indicating whether or not to use fhi_data in simulation
        """
        self.horizon = horizon
        self.population = population
        self.epidemic_function = epidemic_function
        self.state = initial_state
        self.path = [self.state]
        self.decision_period = decision_period
        self.fhi_data = fhi_data
        self.verbose = verbose

        policies = {
            "no_vaccines": self._no_vaccines,
            "random": self._random_policy,
            "population_based": self._population_based_policy,
            "infection_based": self._infection_based_policy
        }

        self.policy = policies[policy]

    def run(self):
        """ Updates states from current time_step to a specified horizon

        Returns
            A path that shows resulting traversal of states
        """
        run_range = range(self.state.time_step, self.horizon) if self.verbose else tqdm(range(self.state.time_step, self.horizon))
        for _ in run_range:
            if self.verbose: print(self.state, end="\n"*3)
            self.update_state()
            if np.sum(self.state.R) / np.sum(self.population.population) > 0.7: # stop if recovered population is 70 % of total population
                print("Reached stop-criteria. Recovered population > 70%.")
                break
            if np.sum(self.state.E1) < 1: # stop if infections are zero
                print("Reached stop-criteria. Infected population is zero.")
                break
        return self.path

    def get_exogenous_information(self, state):
        """ Recieves the exogenous information at time_step t

        Parameters
            t: time_step
            state: state that 
        Returns:
            returns a dictionary of information contain 'alphas', 'vaccine_supply', 'contact_matrices_weights'
        """
        alphas = [1, 1, 1, 1, 0.1]
        contact_matrices_weights =  np.array([0.31, 0.24, 0.16, 0.29])
        vaccine_supply = np.ones((356,5))

        information = {'alphas': alphas, 'vaccine_supply': vaccine_supply, 'contact_matrices_weights':contact_matrices_weights}

        if self.fhi_data is not None:
            sim_step = state.time_step // self.decision_period
            information['vaccine_supply'] = self.fhi_data.iloc[sim_step,:]['vaccine_supply_new']
            alphas = [self.fhi_data.iloc[sim_step,:]['alpha_s'],
                      self.fhi_data.iloc[sim_step,:]['alpha_e1'],
                      self.fhi_data.iloc[sim_step,:]['alpha_e2'], 
                      self.fhi_data.iloc[sim_step,:]['alpha_a'],
                      self.fhi_data.iloc[sim_step,:]['alpha_i']]
            information['alphas'] = alphas
            weights =[self.fhi_data.iloc[sim_step,:]['w_c1'],
                      self.fhi_data.iloc[sim_step,:]['w_c2'],
                      self.fhi_data.iloc[sim_step,:]['w_c3'], 
                      self.fhi_data.iloc[sim_step,:]['w_c4']]
            information['contact_matrices_weights'] = weights
        
        return information

    def update_state(self, decision_period=28):
        """ Updates the state of the decision process.

        Parameters
            decision_period: number of periods forward in time that the decision directly affects
        """
        decision = self.policy()
        information = self.get_exogenous_information(self.state)
        self.state = self.state.get_transition(decision, information, self.epidemic_function.simulate, decision_period)
        self.path.append(self.state)

    def _no_vaccines(self):
        """ Define allocation of vaccines to zero

        Returns
            a vaccine allocation of shape (#decision periods, #regions, #age_groups)
        """
        pop = self.population[self.population.columns[2:-1]].to_numpy(dtype="float64")
        n_regions, n_age_groups = pop.shape
        return np.zeros(shape=(self.decision_period, n_regions, n_age_groups))

    def _random_policy(self):
        """ Define allocation of vaccines based on random distribution

        Returns
            a vaccine allocation of shape (#decision periods, #regions, #age_groups)
        """
        pop = self.population[self.population.columns[2:-1]].to_numpy(dtype="float64")
        n_regions, n_age_groups = pop.shape
        vaccine_allocation = np.array([np.zeros(pop.shape) for _ in range(self.decision_period)])
        demand = self.state.S.copy()
        vacc_available = self.state.vaccines_available
        while vacc_available > 0:
            period, region, age_group = np.random.randint(self.decision_period), np.random.randint(n_regions), np.random.randint(n_age_groups)
            if demand[region][age_group] > 100: 
                vacc_available -= 1
                vaccine_allocation[period][region][age_group] += 1
                demand[region][age_group] -= 1

        return vaccine_allocation

    def _population_based_policy(self):
        """ Define allocation of vaccines based on number of inhabitants in each region

        Returns
            a vaccine allocation of shape (#decision periods, #regions, #age_groups)
        """
        vaccine_allocation = []
        for period in range(self.decision_period):
            total_allocation = self.state.vaccines_available * self.state.S/np.sum(self.state.S)
            vaccine_allocation.append(total_allocation/self.decision_period)
        return vaccine_allocation

    def _infection_based_policy(self):
        """ Define allocation of vaccines based on number of infected in each region

        Returns
            a vaccine allocation of shape (#decision periods, #regions, #age_groups)
        """
        vaccine_allocation = []
        for period in range(self.decision_period):
            total_allocation = self.state.vaccines_available * self.state.E1/np.sum(self.state.E1)
            vaccine_allocation.append(total_allocation/self.decision_period)
        return vaccine_allocation