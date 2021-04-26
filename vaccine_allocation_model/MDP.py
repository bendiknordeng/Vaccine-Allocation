from covid.utils import get_wave_weeks
from vaccine_allocation_model.State import State
import numpy as np
from tqdm import tqdm
import pandas as pd
from datetime import timedelta

class MarkovDecisionProcess:
    def __init__(self, config, decision_period, population, epidemic_function, 
                initial_state, horizon, policy, verbose, historic_data=None):
        """ Initializes an instance of the class MarkovDecisionProcess, that administrates

        Parameters
            OD_matrices: Origin-Destination matrices giving movement patterns between regions
            population: A DataFrame with region_id, region_name and population
            epidemic_function: An epidemic model that enables simulation of the decision process
            vaccine_supply: Information about supply of vaccines, shape e.g. (#decision_period, #regions)
            horizon: The amount of decision_periods the decision process is run 
            decision_period: The number of time steps that every decision directly affects
            policy: How the available vaccines should be distributed.
            historic_data: dataframe, or None indicating whether or not to use fhi_data in simulation
        """
        self.config = config
        self.decision_period = decision_period
        self.horizon = horizon
        self.population = population
        self.epidemic_function = epidemic_function
        self.state = initial_state
        self.historic_data = historic_data
        self.policy_name = policy
        self.verbose = verbose
        self.policy = {
            "no_vaccines": self._no_vaccines,
            "random": self._random_policy,
            "susceptible_based": self._susceptible_based_policy,
            "infection_based": self._infection_based_policy,
            "adults_first": self._adults_first_policy,
            "oldest_first": self._oldest_first_policy,
        }[policy]
        self.path = [self.state]
        self.wave_weeks = get_wave_weeks(self.horizon)

    def run(self):
        """ Updates states from current time_step to a specified horizon

        Returns
            A path that shows resulting traversal of states
        """
        print(f"\033[1mRunning MDP with policy: {self.policy_name}\033[0m")
        run_range = range(self.state.time_step, self.horizon) if self.verbose else tqdm(range(self.state.time_step, self.horizon))
        for week in run_range:
            if self.verbose: print(self.state, end="\n"*2)
            if np.sum(self.state.R) / np.sum(self.population.population) > 0.9: # stop if recovered population is 70 % of total population
                print("\033[1mReached stop-criteria. Recovered population > 90%.\033[0m\n")
                break
            if np.sum([self.state.E1, self.state.E2, self.state.A, self.state.I]) < 0.1: # stop if infections are zero
                print("\033[1mReached stop-criteria. Infected population is zero.\033[0m\n")
                break
            self.update_state()

    def get_exogenous_information(self, state):
        """ Recieves the exogenous information at time_step t

        Parameters
            t: time_step
            state: state that 
        Returns:
            returns a dictionary of information contain 'alphas', 'vaccine_supply', 'contact_matrices_weights', 'wave_incline', 'wave_decline'
        """
        today = pd.Timestamp(state.date)
        end_of_decision_period = pd.Timestamp(state.date+timedelta(self.decision_period//self.config.periods_per_day))
        mask = (self.historic_data['date'] > today) & (self.historic_data['date'] <= end_of_decision_period)
        week_data = self.historic_data[mask]
        if week_data.empty:
            vaccine_supply = np.zeros(self.state.S.shape)
        else:
            vaccine_supply = int(week_data['vaccine_supply_new'].sum()/2) # supplied vaccines need two doses, model uses only one dose

        contact_weights, alphas = self._map_infection_to_control_measures(self.state.contact_weights, self.state.alphas)
        information = {'alphas': alphas, 
                       'vaccine_supply': vaccine_supply,
                       'contact_weights': contact_weights}
        return information

    def update_state(self, decision_period=28):
        """ Updates the state of the decision process.

        Parameters
            decision_period: number of periods forward whein time that the decision directly affects
        """
        decision = self.policy()
        information = self.get_exogenous_information(self.state)
        self.state = self.state.get_transition(decision, information, self.epidemic_function.simulate, decision_period)
        self.path.append(self.state)

    def _map_infection_to_control_measures(self, previous_cw, previous_alphas):
        min_cw, max_cw = np.array(self.config.min_contact_weights), np.array(self.config.initial_contact_weights)
        min_alphas, max_alphas = np.array(self.config.min_alphas), np.array(self.config.initial_alphas)
        new_cw = previous_cw.copy()
        new_alphas = previous_alphas.copy()
        simulation_week = self.state.time_step//self.decision_period
        if simulation_week in self.wave_weeks:
            wave_strength = np.random.normal(2, 0.1)
            if self.verbose:
                print("\033[1mInfection wave\033[0m")
                print(f"Wavestrength: {wave_strength}\n\n")
                new_cw = new_cw * wave_strength
                new_alphas = new_alphas * wave_strength

        if len(self.path) > 2:
            new_infected_current = np.sum(self.state.new_infected)
            new_infected_historic = np.sum(self.path[-3].new_infected)
            n_days = self.decision_period/self.config.periods_per_day
            if new_infected_historic > 0:
                infection_rate = new_infected_current/new_infected_historic
            else:
                infection_rate = 0
            maximum_new_infected = max([np.sum(state.new_infected) for state in self.path])
            infected_per_100k = np.sum(self.state.I)/(self.population.population.sum()/1e5)
            increasing_trend = infection_rate > 1.15 and new_infected_current > 0.1 * maximum_new_infected
            decreasing_trend = infection_rate < 0.85
            slope = (new_infected_current-new_infected_historic)/n_days
            factor = 4 /((1 + np.exp(0.005*slope)) * (1 + np.exp(0.01*infected_per_100k)))

            if self.verbose:
                if increasing_trend:
                    print("\033[1mIncreasing trend\033[0m")
                elif decreasing_trend:
                    print("\033[1mDecreasing trend\033[0m")
                else:
                    print("\033[1mNeutral trend\033[0m")
                print(f"R_eff: {self.state.r_eff:.2f}")
                print(f"Infected per 100k: {infected_per_100k:.1f}")
                print(f"New infected last week: {new_infected_historic}")
                print(f"New infected current week: {new_infected_current}")
                print(f"Maximum new infected: {maximum_new_infected}")
                print(f"Current infections/last week infections: {infection_rate:.3f}")
                print(f"Change in new infected per day: {slope:.3f}")
                print(f"Control measure factor: {factor:.3f}")
                print(f"Previous weights: {previous_cw}")
                print(f"Previous alphas: {previous_alphas}\n\n")

            if increasing_trend or decreasing_trend:
                new_cw = (new_cw * factor).clip(min=min_cw, max=max_cw)
                new_alphas = (new_alphas * factor).clip(min=min_alphas, max=max_alphas)
                return new_cw, new_alphas
                    
        new_cw = new_cw.clip(min=min_cw, max=max_cw)
        new_alphas = new_alphas.clip(min=min_alphas, max=max_alphas)
        return new_cw, new_alphas

    def _no_vaccines(self):
        """ Define allocation of vaccines to zero

        Returns
            a vaccine allocation of shape (#decision periods, #regions, #age_groups)
        """
        pop = self.population[self.population.columns[2:-1]].to_numpy(dtype="float64")
        return np.zeros(pop.shape)

    def _random_policy(self):
        """ Define allocation of vaccines based on random distribution

        Returns
            a vaccine allocation of shape (#decision periods, #regions, #age_groups)
        """
        pop = self.population[self.population.columns[2:-1]].to_numpy(dtype="float64")
        n_regions, n_age_groups = pop.shape
        vaccine_allocation = np.zeros((n_regions, n_age_groups))
        demand = self.state.S.copy()-(1-self.config.efficacy)*self.state.V.copy()
        M = self.state.vaccines_available
        while M > 0:
            possible_regions = np.nonzero(demand > 0)[0]
            region = np.random.choice(possible_regions)
            possible_age_groups = np.nonzero(demand[region] > 0)[0]
            age_group = np.random.choice(possible_age_groups)
            allocation = np.min([M, demand[region][age_group], 1]) # consider fractional populations
            M -= allocation
            vaccine_allocation[region][age_group] += allocation
            demand[region][age_group] -= allocation
        decision = np.minimum(demand, vaccine_allocation).clip(min=0)
        return decision

    def _susceptible_based_policy(self):
        """ Define allocation of vaccines based on number of susceptible inhabitants in each region

        Returns
            a vaccine allocation of shape (#decision periods, #regions, #age_groups)
        """
        pop = self.population[self.population.columns[2:-1]].to_numpy(dtype="float64")
        vaccine_allocation = np.zeros(pop.shape)
        demand = self.state.S.copy()-(1-self.config.efficacy)*self.state.V.copy()
        M = self.state.vaccines_available
        if M > 0:
            vaccine_allocation = M * demand/np.sum(demand)
            decision = np.minimum(demand, vaccine_allocation).clip(min=0)
            return decision
        return vaccine_allocation

    def _infection_based_policy(self):
        """ Define allocation of vaccines based on number of infected in each region

        Returns
            a vaccine allocation of shape (#decision periods, #regions, #age_groups)
        """
        pop = self.population[self.population.columns[2:-1]].to_numpy(dtype="float64")
        vaccine_allocation = np.zeros(pop.shape)
        total_infection = np.sum(self.state.I)
        M = self.state.vaccines_available
        if M > 0:
            if total_infection > 0:
                demand = self.state.S.copy()-(1-self.config.efficacy)*self.state.V.copy()
                infection_density = self.state.I.sum(axis=1)/total_infection
                regional_allocation = M * infection_density
                vaccine_allocation = demand * regional_allocation.reshape(-1,1)/demand.sum(axis=1).reshape(-1,1)
                decision = np.minimum(demand, vaccine_allocation).clip(min=0)
                return decision
            else:
                return self._susceptible_based_policy()
        return vaccine_allocation

    def _adults_first_policy(self):
        """ Define allocation of vaccines based on age, prioritize the middle groups (epidemic drivers)

        Returns
            a vaccine allocation of shape (#decision periods, #regions, #age_groups)
        """
        pop = self.population[self.population.columns[2:-1]].to_numpy(dtype="float64")
        vaccine_allocation = np.zeros(pop.shape)
        M = self.state.vaccines_available
        demand = self.state.S.copy()-(1-self.config.efficacy)*self.state.V.copy()
        if M > 0:
            def find_prioritized_age_group(demand):
                for a in [3,4,5,6,7,2,1,0]:
                    if np.sum(demand[:,a]) > 0:
                        return a
                        
            age_group = find_prioritized_age_group(demand)
            allocation = np.zeros(pop.shape)
            age_group_demand = demand[:,age_group]
            total_age_group_demand = np.sum(age_group_demand)
            if M > total_age_group_demand:
                age_allocation = age_group_demand
                allocation[:,age_group] = age_allocation
                demand[:,age_group] -= allocation[:,age_group]
                M -= total_age_group_demand
                age_group = find_prioritized_age_group(demand)
                age_group_demand = demand[:,age_group]
                total_age_group_demand = np.sum(age_group_demand)
            age_allocation = M * age_group_demand/total_age_group_demand
            M -= age_allocation
            allocation[:,age_group] = age_allocation
            vaccine_allocation = allocation
            demand[:,age_group] -= allocation[:,age_group]
            decision = np.minimum(demand, vaccine_allocation).clip(min=0)
            return decision
        return vaccine_allocation

    def _oldest_first_policy(self):
        """ Define allocation of vaccines based on age, prioritize the oldest group

        Returns
            a vaccine allocation of shape (#decision periods, #regions, #age_groups)
        """
        pop = self.population[self.population.columns[2:-1]].to_numpy(dtype="float64")
        vaccine_allocation = np.zeros(pop.shape)
        M = self.state.vaccines_available
        demand = self.state.S.copy()-(1-self.config.efficacy)*self.state.V.copy()
        if M > 0:
            def find_prioritized_age_group(demand):
                for age_group in range(pop.shape[1]-1,0,-1):
                    if np.round(np.sum(demand[:,age_group])) > 0:
                        return age_group

            age_group = find_prioritized_age_group(demand)
            allocation = np.zeros(pop.shape)
            age_group_demand = demand[:,age_group]
            total_age_group_demand = np.sum(age_group_demand)
            if M > total_age_group_demand:
                age_allocation = age_group_demand
                allocation[:,age_group] = age_allocation
                demand[:,age_group] -= allocation[:,age_group]
                M -= total_age_group_demand
                age_group = find_prioritized_age_group(demand)
                age_group_demand = demand[:,age_group]
                total_age_group_demand = np.sum(age_group_demand)
            age_allocation = M * age_group_demand/total_age_group_demand
            M -= total_age_group_demand
            allocation[:,age_group] = age_allocation
            vaccine_allocation = allocation
            demand[:,age_group] -= allocation[:,age_group]
            decision = np.minimum(demand, vaccine_allocation).clip(min=0)
            return decision
        return vaccine_allocation