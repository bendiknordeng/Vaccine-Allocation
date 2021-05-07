import numpy as np

class SEAIR:
    def __init__(self, commuters, contact_matrices, population, age_group_flow_scaling, 
                death_rates, config, paths, include_flow, stochastic):
        """ 
        Parameters:
            commuter_effect: Matrix of the percentage population growth or decline during working hours 
            contact_matrices: Contact matrices between age groups
            population: pd.DataFrame with columns region_id, region_name, population (quantity)
            config: named tuple with following parameters
                age_group_flow_scaling: list of scaling factors for flow of each age group
                R0: Basic reproduction number (e.g 2.4)
                efficacy: vaccine efficacy (e.g 0.95)
                proportion_symptomatic_infections: Proportion of symptomatic infections(e.g 0.8)
                latent_period: Time before vaccine is effective (e.g 5.1*4)
                recovery_period: Time to recover from receiving the virus to not being  (e.g 21'4)
                pre_isolation_infection_period: Pre-isolation infection period (e.g 4.6*4)
                post_isolation_recovery_period: Post-isolation recovery period (e.g 16.4*4)
                fatality_rate_symptomatic: Fatality rate for people that experience symptoms (e.g 0.01)
            include_flow: boolean, true if we want to model population flow between regions
            hidden_cases: boolean, true if we want to model hidden cases of infection
            write_to_csv: boolean, true if we want to write results to csv
            write_weekly: boolean, false if we want to write daily results, true if weekly
        """
        self.periods_per_day = config.periods_per_day
        self.time_delta = config.time_delta
        self.commuters = commuters
        self.contact_matrices = contact_matrices
        self.population = population
        self.age_group_flow_scaling = age_group_flow_scaling
        self.fatality_rate_symptomatic = death_rates
        self.efficacy = config.efficacy
        self.latent_period = config.latent_period
        self.proportion_symptomatic_infections = config.proportion_symptomatic_infections
        self.presymptomatic_infectiousness = config.presymptomatic_infectiousness
        self.asymptomatic_infectiousness = config.asymptomatic_infectiousness
        self.presymptomatic_period = config.presymptomatic_period
        self.postsymptomatic_period = config.postsymptomatic_period
        self.recovery_period = self.presymptomatic_period + self.postsymptomatic_period
        self.stochastic = stochastic
        self.include_flow = include_flow
        self.paths = paths

    def simulate(self, state, decision, decision_period, information):
        """  simulates the development of an epidemic as modelled by current parameters
        
        Parameters:
            state: State object with values for each compartment
            decision: Vaccine allocation for each period for each region, shape (decision_period, nr_regions)
            decision_period: number of steps the simulation makes
            information: dict of exogenous information for each region, shape (decision_period, nr_regions, nr_regions)
            write_to_csv: Bool, True if history is to be saved as csv
            write_weekly: Bool, True if history is to be sampled on a weekly basis
            hidden_cases: Bool, True if random hidden infections is to be included in modelling
        Returns:
            res: accumulated SEIR values for all regions as whole (decision_period, )
            total_new_infected.sum(): accumulated infected for the decision_period, float.
            history: compartment values for each region, time step, and age group shape: (#decision_period,  #compartments, #regions, #age groups)
        """
        # Meta-parameters
        S, E1, E2, A, I, R, D, V = state.get_compartments_values()
        n_regions, n_age_groups = S.shape
        age_flow_scaling = np.array(self.age_group_flow_scaling)

        # Get information data
        R_eff = information['R']
        alphas = information['alphas']
        C = self.generate_weighted_contact_matrix(information['contact_weights'])
        visitors = self.commuters[0] * information['flow_scale']
        OD = self.commuters[1] * information['flow_scale']

        # Initialize variables for saving history
        total_new_infected = np.zeros(shape=(decision_period, n_regions, n_age_groups))
        total_new_deaths = np.zeros(shape=(decision_period, n_regions, n_age_groups))
        
        # Probabilities
        beta = R_eff/self.recovery_period
        r_e = self.presymptomatic_infectiousness
        r_a = self.asymptomatic_infectiousness
        p = self.proportion_symptomatic_infections
        delta = self.fatality_rate_symptomatic
        epsilon = self.efficacy
        
        # Rates
        sigma = 1/(self.latent_period * self.periods_per_day)
        alpha = 1/(self.presymptomatic_period * self.periods_per_day)
        omega = 1/(self.postsymptomatic_period * self.periods_per_day)
        gamma = 1/(self.recovery_period * self.periods_per_day)

        # Run simulation
        for i in range(decision_period):
            timestep = (state.date.weekday() * self.periods_per_day + i) % decision_period

            # Vaccinate before flow
            new_V = decision/decision_period
            successfully_new_V = epsilon * new_V
            S = S - successfully_new_V
            R = R + successfully_new_V
            V = V + new_V

            # Update population to account for new deaths
            N = sum([S, E1, E2, A, I, R])
            
            # Calculate new infected from commuting
            commuter_cases = 0
            working_hours = timestep < (self.periods_per_day * 5) and timestep % self.periods_per_day == 2
            if self.include_flow and working_hours:
                # Define current transmission of infection with commuters
                lam_j = np.clip(beta * (r_e * E2 + r_a * A + I)/visitors, 0, 1)
                commuter_cases = S/N * np.array([np.matmul(OD * age_flow_scaling[a], lam_j[:,a]) for a in range(len(age_flow_scaling))]).T
                if self.stochastic:
                    commuter_cases = np.random.poisson(commuter_cases)

            # Define current transmission of infection without commuters
            lam_i = np.clip(beta * (alphas[0] * r_e * E2 + alphas[1] * r_a * A + alphas[2] * I), 0, 1)
            contact_cases = S/N * np.matmul(lam_i, C)
            if self.stochastic:
                contact_cases = np.random.poisson(contact_cases)

            new_E1  = np.clip(contact_cases + commuter_cases, None, S)
            new_E2  = E1 * sigma * p
            new_A   = E1 * sigma * (1 - p)
            new_I   = E2 * alpha
            new_R_A = A  * gamma
            new_R_I = I  * (np.ones(len(delta)) - delta) * omega
            new_D   = I  * delta * omega

            # Calculate values for each compartment
            S  = S - new_E1
            E1 = E1 + new_E1 - new_E2 - new_A
            E2 = E2 + new_E2 - new_I
            A  = A + new_A - new_R_A
            I  = I + new_I - new_R_I - new_D
            R  = R + new_R_I + new_R_A
            D  = D + new_D

            # Save number of new infected
            total_new_infected[i] = new_I
            total_new_deaths[i] = new_D

        return S, E1, E2, A, I, R, D, V, total_new_infected.sum(axis=0), total_new_deaths.sum(axis=0)

    def generate_weighted_contact_matrix(self, contact_weights):
        """ Scales the contact matrices with weights, and return the weighted contact matrix used in modelling

        Parameters
            weights: list of floats indicating the weight of each contact matrix for school, workplace, etc. 
        Returns
            weighted contact matrix used in modelling
        """
        C = self.contact_matrices
        return np.sum(np.array([np.array(C[i])*contact_weights[i] for i in range(len(C))]), axis=0)
