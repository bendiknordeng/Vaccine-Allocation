import numpy as np
from collections import namedtuple
from covid import utils
import os
from random import randint, uniform

class SEAIQR:
    def __init__(self, OD, population, R0=2.4, DE= 5.6*4, DI= 5.2*4, hospitalisation_rate=0.1, hospital_duration=15*4,
    efficacy=0.95,  proportion_symptomatic_infections=0.8, latent_period=5.1*4, recovery_period=21*4,
    pre_isolation_infection_period=4.6*4, post_isolation_recovery_period=16.4*4, fatality_rate_symptomatic=0.01*4,
    immunity_duration=365*4
    ):
        """ 
        Parameters
        - self.par: parameters {
                    OD: Origin-Destination matrix
                    population: pd.DataFrame with columns region_id, region_name, population (quantity)
                    R0: Basic reproduction number (e.g 2.4)
                    DE: Incubation period (e.g 5.6 * 4)        # Needs to multiply by 12 to get one day effects
                    DI: Infectious period (e.g 5.2 * 4)
                    hospitalisation_rate: Percentage of people that will be hospitalized (e.g 0.1)
                    hospital_duration: Length of hospitalization (e.g 15*4) }
                    efficacy: vaccine efficacy (e.g 0.95)
                    proportion_symptomatic_infections: Proportion of symptomatic infections(e.g 0.8)
                    latent_period: Time before vaccine is effective (e.g 5.1*4)
                    recovery_period: Time to recover from receiving the virus to not being  (e.g 21'4)
                    pre_isolation_infection_period: Pre-isolation infection period (e.g 4.6*4)
                    post_isolation_recovery_period: Post-isolation recovery period (e.g 16.4*4)
                    fatality_rate_symptomatic: Fatality rate for people that experience symptoms (e.g 0.01)
                    immunity_duration: Immunity duration of vaccine or after having the disease (e.g 365*4)
         """
        self.paths = utils.create_named_tuple('filepaths.txt')
        param = namedtuple('param', 'OD population R0 DE DI hospitalisation_rate hospital_duration efficacy proportion_symptomatic_infections latent_period recovery_period pre_isolation_infection_period post_isolation_recovery_period fatality_rate_symptomatic immunity_duration')
        self.par = param(
                        OD=OD,
                        population=population, 
                        R0=R0, 
                        DE=DE, 
                        DI=DI, 
                        hospitalisation_rate=hospitalisation_rate, 
                        hospital_duration=hospital_duration,
                        efficacy=efficacy,  
                        proportion_symptomatic_infections=proportion_symptomatic_infections, 
                        latent_period=latent_period, 
                        recovery_period=recovery_period,
                        pre_isolation_infection_period=pre_isolation_infection_period, 
                        post_isolation_recovery_period=post_isolation_recovery_period, 
                        fatality_rate_symptomatic=fatality_rate_symptomatic,
                        immunity_duration=immunity_duration
                        )

    def scale_flow(self, alpha):
        """ Scales flow of individuals between regions

        Parameters
            alpha: array of scalers that adjust flows for a given compartment and region
        Returns
            realflow, scaled flow
        """
        realflow = self.par.OD.copy() 
        realflow = realflow / realflow.sum(axis=2)[:,:, np.newaxis]  # Normalize flow
        realflow = alpha * realflow 
        return realflow

    def add_hidden_cases(self, s_vec, i_vec, new_i):
        """ Adds cases to the infection compartment, to represent hidden cases

        Parameters
            s_vec: array of susceptible in each region
            i_vec: array of infected in each region
            new_i: array of new cases of infected individuals
        Returns
            new_i, an array of new cases including hidden cases
        """
        share = 0.1 # maximum number of hidden infections
        i_vec = i_vec.reshape(-1) # ensure correct shape
        s_vec = s_vec.reshape(-1) # ensure correct shape
        new_i = new_i.reshape(-1) # ensure correct shape
        for i in range(len(i_vec)):
            if i_vec[i] < 0.5:
                new_infections = uniform(0, 0.01) # introduce infection to region with little infections
            else:
                new_infections = randint(0, min(int(i_vec[i]*share), 1))
            if s_vec[i] > new_infections:
                new_i[i] += new_infections
        return new_i

    def simulate(self, state, decision, decision_period, information, hidden_cases=True, write_to_csv=False, write_weekly=True):
        """  simulates the development of an epidemic as modelled by current parameters
        
        Parameters:
            state: State object with values for each compartment
            decision: Vaccine allocation for each period for each region, shape (decision_period, nr_regions)
            decision_period: number of steps the simulation makes
            information: dict of exogenous information for each region, shape (decision_period, nr_regions, nr_regions)
            write_to_csv: Bool, True if history is to be saved as csv
            write_weekly: Bool, True if history is to be sampled on a weekly basis
        Returns:
            res: accumulated SEIR values for all regions as whole (decision_period, )
            total_new_infected.sum(): accumulated infected for the decision_period, float.
            history: SEIRHV for each region for each time step (decision_period,  number_compartments, number_of_regions)
        """
        # Meta-parameters
        compartments = 'SEAIQRDVH'
        k = len(compartments)
        r = self.par.OD.shape[0]
        n = self.par.OD.shape[1]
        
        S_vec = state.S
        E_vec = state.E
        A_vec = state.A
        I_vec = state.I
        Q_vec = state.Q
        R_vec = state.R
        D_vec = state.D
        V_vec = state.V
        H_vec = state.H
        
        result = np.zeros((decision_period, k))
        result[0,:] = [S_vec.sum(), E_vec.sum(), A_vec.sum(), I_vec.sum(), Q_vec.sum(), R_vec.sum(), D_vec.sum(), V_vec.sum(), 0]
        
        # Realflows for different comself.partments 
        alpha_s, alpha_e, alpha_a, alpha_i, alpha_q, alpha_r = information['alphas'] # They currently have the same values
        realflow_s = self.scale_flow(alpha_s)
        realflow_e = self.scale_flow(alpha_e)
        realflow_a = self.scale_flow(alpha_a)
        realflow_i = self.scale_flow(alpha_i)
        realflow_q = self.scale_flow(alpha_q)
        realflow_r = self.scale_flow(alpha_r)
        
        history = np.zeros((decision_period, k, n))
        history[0,0,:] = S_vec
        history[0,1,:] = E_vec
        history[0,2,:] = A_vec
        history[0,3,:] = I_vec
        history[0,4,:] = Q_vec
        history[0,5,:] = R_vec
        history[0,6,:] = D_vec
        history[0,7,:] = V_vec
        history[0,8,:] = H_vec


        total_new_infected = np.zeros(decision_period+1)
        
        # run simulation
        for i in range(0, decision_period - 1):
            # Finds the flow between regions for each compartment 
            realOD_s = realflow_s[i % r]
            realOD_e = realflow_e[i % r]
            realOD_a = realflow_a[i % r] 
            realOD_i = realflow_i[i % r]
            realOD_q = realflow_q[i % r] 
            realOD_r = realflow_r[i % r]
            
            # Finds the decision - number of vaccines to be allocated to each region for a specific time period
            v = decision[i % r]

            # Calculate values for each arrow in epidemic model 
            newS = R_vec / self.par.immunity_duration # Ignored for now
            newE = S_vec * (A_vec + I_vec) / self.par.population.population.to_numpy(dtype='float64') * (self.par.R0 / self.par.DI)  # Need to change this to force of infection 
            newA = (1 - self.par.proportion_symptomatic_infections) * E_vec / self.par.latent_period
            newI = self.par.proportion_symptomatic_infections *  E_vec / self.par.latent_period
            newQ = I_vec /  self.par.pre_isolation_infection_period  
            newR_fromA = A_vec / self.par.recovery_period
            newR_fromQ = Q_vec * (1- self.par.fatality_rate_symptomatic) / self.par.recovery_period 
            newR_fromV = V_vec/self.par.latent_period
            newD = Q_vec * self.par.fatality_rate_symptomatic / self.par.recovery_period
            newV = v * self.par.efficacy

            # Calculate values for each compartment
            S_vec = S_vec - newV - newE
            S_vec = (S_vec 
                + np.matmul(S_vec.reshape(1,n), realOD_s)
                - S_vec * realOD_s.sum(axis=1))
            E_vec = E_vec + newE - newI - newA
            E_vec = (E_vec 
                + np.matmul(E_vec.reshape(1,n), realOD_e)
                - E_vec * realOD_e.sum(axis=1))
            A_vec = A_vec + newA - newR_fromA
            A_vec = (A_vec 
                + np.matmul(A_vec.reshape(1,n), realOD_a)
                - A_vec * realOD_a.sum(axis=1))
            I_vec = I_vec + newI - newQ
            I_vec = (I_vec 
                + np.matmul(I_vec.reshape(1,n), realOD_i)
                - I_vec * realOD_i.sum(axis=1))
            Q_vec = Q_vec + newQ - newR_fromQ - newD
            Q_vec = (Q_vec 
                + np.matmul(Q_vec.reshape(1,n), realOD_q)
                - Q_vec * realOD_q.sum(axis=1))
            R_vec = R_vec + newR_fromQ + newR_fromA + newR_fromV
            R_vec = (R_vec 
                + np.matmul(R_vec.reshape(1,n), realOD_r)
                - R_vec * realOD_r.sum(axis=1))
            D_vec = D_vec + newD
            V_vec = V_vec + newV - newR_fromV

            # Add the accumulated numbers to results
            result[i + 1,:] = [S_vec.sum(), E_vec.sum(), A_vec.sum(), I_vec.sum(), Q_vec.sum(), R_vec.sum(),  D_vec.sum(), H_vec.sum(), V_vec.sum()]
            
            # Add number of hospitalized 
            total_new_infected[i + 1] = newI.sum()
            result[i + 1, 8] = total_new_infected[max(0, i - self.par.hospital_duration) : i].sum() * self.par.hospitalisation_rate
            
            history[i + 1,0,:] = S_vec
            history[i + 1,1,:] = E_vec
            history[i + 1,2,:] = A_vec
            history[i + 1,3,:] = I_vec
            history[i + 1,4,:] = Q_vec
            history[i + 1,5,:] = R_vec
            history[i + 1,6,:] = D_vec
            history[i + 1,7,:] = V_vec
            history[i + 1,8,:] = H_vec

        if write_to_csv:
            utils.write_history(write_weekly,
                                history, 
                                self.par.population, 
                                state.time_step, 
                                self.paths.results_weekly, 
                                self.paths.results_history)
        
        return result, total_new_infected.sum(), history