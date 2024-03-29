#!/usr/bin/env python3

# Author: Minyan Zhong
# Development starts in July, 2018

import os
import sys
import pickle
import shelve
import time
import copy

import numpy as np
from scipy import stats

import matplotlib.pyplot as plt

import datetime
from datetime import date

from configure import configure
from display import display
from solvers import solvers

class estimate(configure):
    def __init__(self, param_file=None):

        if param_file:
            super(estimate,self).__init__(param_file)

            # Do the preparation to load data
            self.preparation()

            # Initializing visualization library
            self.display = display(param_file)

        else:
            raise Exception("Need to provide parameter file to class inversion")

    def set_task_name(self, task_name, sub_task_name=None):
    
        self.task_name = task_name

        self.sub_task_name = sub_task_name

    def estimate(self, point_set, tracks_set):

        ### Get data either from simulation or real data ###

        # Find the info
        test_id = self.test_id

        data_mode = {}
        data_mode['csk'] = self.csk_data_mode
        data_mode['s1'] = self.s1_data_mode

        task_name = self.task_name
        inversion_method = self.inversion_method

        # Num of points.
        n_points = len(point_set)

        # Initialize many sets
        true_tide_vec_set = {}
        tide_vec_set = {}

        tide_vec_uq_set = {}
        resid_of_secular_set = {}
        resid_of_tides_set = {}
        residual_analysis_set = {}

        # For every point, others set is a dictionary
        others_set = {}
        for point in point_set:
            others_set[point] = {}
        
        # test point
        #print('The test point is: ', self.test_point)

        # All variables are dictionary with point_set as the key.
        # Data set formation.
        redo_dataset_formation = 1
        tmp_dataset_pkl_name = "tmp_point_set_dataset.pkl"
        if redo_dataset_formation:
            all_data_set = self.data_set_formation(point_set, tracks_set, data_mode)
            # Save the obtained data set
            with open(tmp_dataset_pkl_name,"wb") as f:
                pickle.dump(all_data_set,f)
        else:
            # Load the obtained data set
            with open(tmp_dataset_pkl_name,"rb") as f:
                all_data_set = pickle.load(f)

        (data_info_set, data_vec_set, noise_sigma_set, offsetfields_set, true_tide_vec_set, height_set, demfactor_set, max_num_of_offsets_set) = all_data_set

        print("Data set formation Done")

        # Put height into others_set
        print("Save and average the extracted height")
        for point in point_set:
            others_set[point]['height'] = np.nanmean(height_set[point]) if len(height_set)>0 else np.nan
        print("Mean height at test point: ", others_set[self.test_point]['height'])

        # Put the number of data points for this point into others set
        for point in point_set:
            others_set[point]['num_of_csk_offset_pairs'] = len([data_info for data_info in data_info_set[point] if data_info[0]=='csk'])
            others_set[point]['max_num_of_csk_offset_pairs'] = max_num_of_offsets_set[point].get('csk',0)

            others_set[point]['num_of_s1_offset_pairs'] = len([data_info for data_info in data_info_set[point] if data_info[0]=='s1'])
            others_set[point]['max_num_of_s1_offset_pairs'] = max_num_of_offsets_set[point].get('s1',0)

        #print(max_num_of_offsets_set)

        print("Number of offset pairs at test point: ", len(offsetfields_set[point]))

        # Check task and inversion method
        if task_name in ["tides_1","tides_3"]:
            assert inversion_method == "Bayesian_Linear"

        if task_name == "tides_2":
            assert inversion_method in ["Bayesian_MCMC", "Nonlinear_Optimization"]

        if task_name in ["tides_1", "tides_3"] and inversion_method == 'Bayesian_Linear':
            
            # Get data error prior.
            invCd_set = self.real_data_uncertainty_set(point_set, data_vec_set, noise_sigma_set)
            print("Data error prior set is Done")

            # Get design matrix.
            linear_design_mat_set_orig = self.build_G_set(point_set, offsetfields_set=offsetfields_set)
    
            #print("Design matrix set (G)\n:", linear_design_mat_set[self.test_point])
            print("Design matrix (obs) set is Done")

            # tides_1: simple linear model
            if task_name == "tides_1":

                enum_grounding_level_int = [None]

            # tides_3: enumerating grounding level
            elif task_name == "tides_3":

                # Set the mode for running

                # Default
                tides_3_mode = "find_optimal_gl"
                gl_option = 'auto'

                if self.sub_task_name == 'x2_run':
                    tides_3_mode = "find_optimal_gl"
                    gl_option = 'manual'
                    gl_list_option = 7

                elif self.sub_task_name == 'find':
                    tides_3_mode = "find_optimal_gl"
                    gl_option = 'auto'

                elif self.sub_task_name.startswith('find_manual'):
                    tides_3_mode = "find_optimal_gl"
                    gl_option = 'manual'
                    gl_list_option = int(self.sub_task_name.split(':')[1])

                elif self.sub_task_name == 'invert':
                    tides_3_mode = "invert_optimal_gl"
                    gl_option = 'auto'

                else:
                    raise ValueError()

                print("tides_3_mode: ", tides_3_mode)

                #print(self.sub_task_name)
                #print(tides_3_mode)
                #print(gl_option)
                #print(stop)

                ## Set the mode (redo, continue) for grounding line level enumeration
                #enum_grounding_run_mode = "redo"
                enum_grounding_run_mode = "continue"

                # Get the completed enumeration of gl
                # Redo: nothing has been done

                current_auto_enum_stage = 0

                if enum_grounding_run_mode == "redo":
                    
                    completed_enum_gl = []

                # Continue: Use what has been done before
                elif enum_grounding_run_mode == "continue":

                    # Load existing tile_set
                    point_result_folder = self.estimation_dir + '/point_result'
                    tile_lon, tile_lat = self.tile
                    point_name = str(tile_lon) + '_' + str(tile_lat)

                    tile_result_pkl_file = point_result_folder + "/" + point_name + ".pkl"
                    if os.path.exists(tile_result_pkl_file):
                        with open(tile_result_pkl_file,"rb") as f:
                            all_sets_former = pickle.load(f)

                        # Load others set
                        others_set = all_sets_former["others_set"]

                        # Load the enumerated values at test point
                        completed_enum_gl = others_set[self.test_point]["grounding_level_model_likelihood"].keys()
                        print("Completed enum gl: ", sorted(completed_enum_gl))

                        # Load the auto enumeration stage if exists
                        if "current_auto_enum_stage" in others_set:
                            #others_set['current_auto_enum_stage'] = 1

                            current_auto_enum_stage = others_set['current_auto_enum_stage']

                    else:
                        completed_enum_gl = []

                else:
                    raise ValueError("Unknown enum grounding run mode")


                ###### Prepare the grounding level values to be enumerated #########
                if gl_option == 'no_grounding':

                    enum_grounding_level = [-10]

                    # convert to integer
                    enum_grounding_level_int = [int(round(gl*(10**6))) if gl else None for gl in enum_grounding_level]
                
                elif gl_option == "manual":

                    enum_grounding_level = None

                    if gl_list_option == 0:
                        enum_space = 0.1
                        gl_low = -4.0
                        gl_high = 0.0

                    elif gl_list_option == 1:
                        enum_space = 0.05
                        gl_low  =   -4.0
                        gl_high =   -0.0

                    elif gl_list_option == 2:
                        enum_space = 0.025
                        gl_low  =   -4.0
                        gl_high =   -0.0

                    elif gl_list_option == 3:
                        enum_space = 0.01
                        gl_low  =   -1.6
                        gl_high =   -1.4

                    elif gl_list_option == 4:
                        enum_space = 0.1
                        gl_low  =   -2
                        gl_high =   -1

                    elif gl_list_option == 5:
                        enum_space = 0.1
                        gl_low  =   -4.0
                        gl_high =   4.0

                    elif gl_list_option == 6:
                        enum_space = 0.1
                        gl_low  =   -4.0
                        gl_high =   -3.0

                    elif gl_list_option == 7:
                        gl_low = -10
                        gl_high = -10
                        enum_space = 1

                    # For Evans synthetic test ephemeral grounding  at -0.5
                    elif gl_list_option == 8:
                        enum_grounding_level = np.asarray([-3.00, -2.10, -1.60, -1.20, -0.90, -0.70, -0.60, -0.56, -0.53, -0.51, -0.5, -0.49, -0.47, -0.44, -0.40, -0.30, -0.10, 0.20, 0.60, 1.10, 1.70, 2.40, 3.00])

                    elif gl_list_option == 9:
                        enum_space = 0.1
                        gl_low = -3.0
                        gl_high = 0.0

                    # For Rutford synthetic test ephemeral grounding at -1.5
                    elif gl_list_option == 10:
                        enum_grounding_level = np.asarray([-4.00, -3.10, -2.60, -2.20, -1.90, -1.70, -1.60, -1.56, -1.53, -1.51, -1.5, -1.49, -1.47, -1.44, -1.40, -1.30, -1.10, -0.80, -0.40, 0.10, 1.00, 3.00, 4.00])

                    # For compare infer K for avaibale and all data. EG at -1.8
                    elif gl_list_option == 11:
                        enum_grounding_level = np.asarray([-3.0, -2.5, -2.0, -1.9, -1.85, -1.83, -1.81, -1.80, -1.79, -1.77, -1.74, -1.7, -1.5, -1.0, -0.0])

                    else:
                        raise ValueError()

                    if enum_grounding_level is None:
                        enum_grounding_level = np.arange(gl_low, gl_high+1e-6, enum_space)
                    
                    print('enum_grounding_level for manual mode: ', enum_grounding_level)

                    # convert to integer
                    enum_grounding_level_int = [int(round(gl*(10**6))) if gl or gl==0 else None for gl in enum_grounding_level]

                    if enum_grounding_run_mode == 'continue':
                        if set(enum_grounding_level_int).issubset(set(completed_enum_gl)):
                            # All grounding levels have been enumerated
                            print("All grounding line values have been completed")
                            enum_grounding_level_int = []
                
                        else:
                            # We have some new values to enumerate
                            enum_grounding_level_int = set(enum_grounding_level_int) - set(completed_enum_gl)
                            print(enum_grounding_level)
                            print(enum_grounding_level_int)
                            enum_grounding_level_int = sorted(list(enum_grounding_level_int))

                    print("Remaining gl values for manual eumeration if passing the ice shelf check: ", enum_grounding_level_int)

                    # Mark that the next stage will be done (for manual mode)
                    # Need to be checked every time in manual mode
                    others_set['current_auto_enum_stage'] = 3
               
                elif gl_option == 'auto':
                    # set the parameters for auto
                    auto_enum_stages = {}

                    auto_gl_option = 0

                    if auto_gl_option == 0:
                        # first enum
                        auto_enum_stages[1] = (None, 0.1)

                        # second enum
                        auto_enum_stages[2] = (0.15, 0.03)

                        # third enum
                        auto_enum_stages[3] = (0.05, 0.01)

                    else:
                        raise ValueError("Unknown auto gl option")

                    # Set the search range parameters for auto
                    # This is designed to be a global control for all values
                    # Range of search
                    if self.proj == 'Rutford':
                        # half range (I use this for manuscripts before 2022.3)
                        #gl_low = -4.0
                        #gl_high = 0.0

                        # full range
                        gl_low  =   -4.0
                        gl_high =   4.0

                    elif self.proj == 'Evans':
                        # half range
                        #gl_low = -3.0
                        #gl_high = 0.0

                        # full range 1 (I use this manuscript before 2022.3))
                        gl_low  =   -3.0
                        gl_high =   3.0


                    else:
                        raise ValueError()

                    print("gl_low: ", gl_low)
                    print("gl_high: ", gl_high)

                    # Derive the gl values to be enumerated
                    if current_auto_enum_stage == 0:

                        # move to stage 1
                        next_auto_enum_stage = current_auto_enum_stage + 1

                        # get enum spacing for stage 1 (0.1 spacing)
                        enum_space = auto_enum_stages[next_auto_enum_stage][1] 

                        enum_grounding_level = np.arange(gl_low, gl_high+1e-6, enum_space)

                        # store the index instead
                        enum_grounding_level_int = np.arange(len(enum_grounding_level))

                        # Create enumeration list for all points
                        enum_grounding_level_auto_mode_set = {}
                        for point in point_set:
                            enum_grounding_level_auto_mode_set[point] = [int(round(gl_low * 10**6)), int(round(enum_space * 10**6))]


                    # Not stage 0 but has reached the final stage
                    elif current_auto_enum_stage < len(auto_enum_stages):

                        # dictionary to what to enumerate for a point
                        enum_grounding_level_auto_mode_set = {}

                        # move to the next stage
                        next_auto_enum_stage = current_auto_enum_stage + 1

                        for point in point_set:
                            optimal_gl = others_set[point]["optimal_grounding_level"]

                            # The optimal_gl can be -10 * 10**6, so the optimal_gl_low may be meaningless
                            # Thie case is taken care of in the sanity check for ice shelf below

                            # If optimal_gl is not NaN
                            if not np.isnan(optimal_gl):
                                optimal_gl_low = optimal_gl/10**6 - auto_enum_stages[next_auto_enum_stage][0]
                            else:
                                # the inversion actually fails, but to make it easier for parallel computation,
                                # set the gl_low to be -4, other values also work
                                if self.proj == 'Rutford':
                                    optimal_gl_low = gl_low
                                elif self.proj == 'Evans':
                                    optimal_gl_low = gl_low
                                else:
                                    raise ValueError()

                            # find the spacing of this stage
                            enum_space = auto_enum_stages[next_auto_enum_stage][1]
                            # set the enum range and spacing for this point
                            enum_grounding_level_auto_mode_set[point] = [int(round(optimal_gl_low * 10**6)), int(round(enum_space * 10**6))]
                            
                            #print(others_set[point]['grounding_level_model_likelihood'])
                            #print(optimal_gl, optimal_gl_low, enum_space, current_auto_enum_stage)

                            if point == self.test_point:
                                print('optimal gl: ', optimal_gl)
                                print('auto_mode: ', enum_grounding_level_auto_mode_set[point])

                        # store the index
                        n_enum = int(round(auto_enum_stages[next_auto_enum_stage][0] * 2 / auto_enum_stages[next_auto_enum_stage][1])) + 1
                        enum_grounding_level_int = np.arange(n_enum)

                    elif current_auto_enum_stage == len(auto_enum_stages):
                        print("The last stage of auto enumeration is done. No need for further enumeration")
                        print("Already find the optimal and is ready for inversion")
                        enum_grounding_level_int = []

                        next_auto_enum_stage = current_auto_enum_stage

                    else:
                        raise ValueError()

                    # show the auto mode state
                    print("Current auto enum stage: ", current_auto_enum_stage)
                    print("Next auto enum stage: ", next_auto_enum_stage)
                    
                    # Mark that the next stage will be done (for auto mode)
                    others_set['current_auto_enum_stage'] = next_auto_enum_stage

                ### End of auto mode for gl_option ###

                elif gl_option == 'external':
                    # If the external grounding file is saved in ${id}_grid_set_others.pkl
                    with open(self.external_grounding_level_file,'rb') as f:
                        external_grounding_level = pickle.load(f)

                    enum_grounding_level_int = [int(round(gl*(10**6))) if gl else None for gl in enum_grounding_level]

                else:
                    raise ValueError("Unknown gl_option")
    
                # To save the computing time, check if the point set is on the ice shelf
                # If not, override all previous settings, and just make the -10 the only enumeration

                # The default check kind is 'southern half'
                point_set_check_kind = 'southern_half'

                if self.point_set_check_kind is not None:
                    point_set_check_kind = self.point_set_check_kind

                if not self.check_point_set_with_requirements(point_set, kind=point_set_check_kind):
                    print("This point_set does not pass the check for coverage, skip enumeration")
                    point_set_on_ice_shelf = False

                    # enforce a single enumeration at -10m
                    enum_grounding_level = [-10]
                    enum_grounding_level_int = [int(round(gl*(10**6))) if gl else None for gl in enum_grounding_level]
                    
                    if set(enum_grounding_level_int).issubset(set(completed_enum_gl)):
                        print("grounding level -10 has been completed")
                        enum_grounding_level_int = []
                    else:
                        # Only keep -10 in the list, if I accidentally enumerated other grounding levels before.
                        enum_grounding_level_int = set(enum_grounding_level_int) - set(completed_enum_gl)
                        enum_grounding_level_int = sorted(list(enum_grounding_level_int))

                    print("Outside of the ice shelf, reset enum grounding level: ", enum_grounding_level_int)
                else:
                    print("This point_set passes the check for coverage, perform enumeration")
                    point_set_on_ice_shelf = True


                ## Check for finding optimal gl or inverting optimal gl
                if tides_3_mode == "find_optimal_gl":
                    if len(enum_grounding_level_int) == 0:
                        print("Already find the optimal and is ready for inversion")
                    else:
                        print("Let's do further enumeration")

                elif tides_3_mode == "invert_optimal_gl":
                    assert len(enum_grounding_level_int)==0, print("there are remaining enumeration to be done")
                    print("Enumeration work is done")
                    print("Invert the optimal gl")
                    enum_grounding_level_int = ['optimal']

                else:
                    raise ValueError("Unknown tides_3_mode")

                print("final enum_grounding_level_int: ", enum_grounding_level_int)

            else:
                raise ValueError("Unknown task name")

            ### Get up displacement set ###
            up_disp_set = self.get_up_disp_set(point_set, offsetfields_set)

            ### Put the lowest tide into others_set
            for point in point_set:
                #tide_height_master, tide_height_slave = up_disp_set[self.test_point]
                tide_height_master, tide_height_slave = up_disp_set[point]

                # If is possible that there is no data, offsetfields_set[point] is []
                if len(tide_height_master) > 0:
                    lowest_tide_height = min(min(tide_height_master),min(tide_height_slave))
                else:
                    lowest_tide_height = None
                
                others_set[point]['lowest_tide_height'] = lowest_tide_height

            ### Main: Loop through the grounding level ###
            for ienum, enum_grounding_level in enumerate(enum_grounding_level_int):

                # Default linear inversion ("tides_1")
                if enum_grounding_level is None:
                     linear_design_mat_set = linear_design_mat_set_orig

                # Nonlinear inversion with the grounding level ("tides_3")
                else:
                    # Make a deep copy of dictionary of design matrix
                    linear_design_mat_set = copy.deepcopy(linear_design_mat_set_orig)

                    # Find the given_grounding_level
                    if enum_grounding_level == 'external':
                        given_grounding_level = external_grounding_level
                        gl_name = "external"

                    elif enum_grounding_level == "optimal":
                        # Load the prescaled optimal grounding level
                        optimal_gl_data_mode = 1
                        # option = 0, use the one in others_set
                        if optimal_gl_data_mode == 0:
                            given_grounding_level = others_set
                        # option = 1, use the one filtered and saved as xyz file
                        elif optimal_gl_data_mode == 1:
                            grounding_level_prescale_xyz_file = os.path.join(self.estimations_dir, str(self.test_id), str(self.test_id) + '_est_others_optimal_grounding_level_prescale.xyz')
                            #print(grounding_level_prescale_xyz_file)
                            data_dict = self.read_xyz_into_dict(grounding_level_prescale_xyz_file)

                            # Set the given grounding level
                            given_grounding_level = {}
                            for point in data_dict:
                                given_grounding_level[point] = {}
                                given_grounding_level[point]['optimal_grounding_level'] = int(round(data_dict[point] * 10**6))
                        else:
                            raise ValueError()

                        gl_name = "optimal"

                    # still in search mode
                    else:
                        if gl_option == 'manual':
                            grounding_level_int = enum_grounding_level

                            # convert integer enumeration to float
                            grounding_level = grounding_level_int / (10**6)
                            print("New enumeration: ", ienum, grounding_level)
                            gl_name = "float"
                            given_grounding_level = grounding_level

                        elif gl_option == 'auto':

                            gl_name = "auto"
                            
                            given_grounding_level = {}
                            grounding_level_int = {}

                            for point in point_set:

                                gl_low_int = enum_grounding_level_auto_mode_set[point][0]
                                gl_enum_spacing_int = enum_grounding_level_auto_mode_set[point][1]

                                # Need to distinguish if the point is on ice shelf
                                if point_set_on_ice_shelf:
                                    grounding_level_int_point = gl_low_int + enum_grounding_level * gl_enum_spacing_int
                                    
                                    # clip the value to be winthin the requred range
                                    #gl_a_min = -4.0
                                    #gl_a_max = +4.0
                                    gl_a_min = gl_low
                                    gl_a_max = gl_high
                                    
                                    grounding_level_int_point = np.clip(grounding_level_int_point, a_min = gl_a_min * 10**6, a_max = gl_a_max * 10**6)
                                else:
                                    # -10 * 10**6
                                    grounding_level_int_point = enum_grounding_level
                                    gl_a_min = gl_low
                                    gl_a_max = gl_high
 
                                # Save to the two dicts
                                grounding_level_int[point] = grounding_level_int_point
                                given_grounding_level[point] = grounding_level_int_point / 10**6

                                if point == self.test_point:
                                    print("Auto mode enumeration at test point: ")
                                    print(given_grounding_level[point], gl_low_int, enum_grounding_level, gl_enum_spacing_int)
                                    print('gl_a_min and max (prescribed, not applicable on points without enumeration): ', gl_a_min, gl_a_max)
                        else:
                            raise ValueError("Unknown gl_option")

                    # Modifying G matrix to add direct modeling of vertical displacement
                    linear_design_mat_set = self.modify_G_set(point_set, linear_design_mat_set, offsetfields_set, up_disp_set, grounding_level = given_grounding_level, gl_name = gl_name)
                    print("Modified matrix (obs) set for tide_3 mode is Done. Matrix shape ", linear_design_mat_set[self.test_point].shape)

                # If invert for secular variation, add three column for G
                if self.est_secular_variation:
                    linear_design_mat_set = self.modify_G_for_secular_variation_set(point_set, linear_design_mat_set, offsetfields_set, data_info_set)
                    print("Modified matrix (obs) set for secular variation is Done. Matrix shape ", linear_design_mat_set[self.test_point].shape)

                # If invert for topographic residual, add another column for G
                if self.est_topo_resid:
                    linear_design_mat_set = self.modify_G_for_topo_resid_set(point_set, linear_design_mat_set, offsetfields_set, data_info_set, demfactor_set)
                    print("Modified matrix (obs) set for topo resid is Done. Matrix shape ", linear_design_mat_set[self.test_point].shape)


                ## The order of making modification is required. 1. tides_3 change 2. secular variation 3. topo resid
                ##########################################################################################################

                # Model prior.
                if ienum == 0:
                    invCm_set = self.model_prior_set(point_set)
                    print("Model prior set Done")
                else:
                    print('Reuse the model prior set')
        
                # Model posterior (Singular matrix will come back with nan).
                Cm_p_set = self.model_posterior_set(point_set, linear_design_mat_set, invCd_set, invCm_set, test_point = self.test_point)
                #print('Model posterior: ',Cm_p_set[self.test_point])
                print("Model posterior set Done")
        
                # Show the model posterior.
                #self.display.show_model_mat(Cm_p_set[self.test_point])
        
                ### Inversion ###
                # Estimate model params.
                model_vec_set = self.param_estimation_set(point_set, linear_design_mat_set, data_vec_set, invCd_set, invCm_set, Cm_p_set)
                #print('model_vec_set: ', model_vec_set)
                print('Model vec set estimation Done')
    
                # Output the result of test_point
                print("***Results of Bayesian linear (test point)")
                bl_model_vec = model_vec_set[self.test_point]
                print("Bayesian linear model: \n")
                print(bl_model_vec)
    
                # Calculale the residual.
                resid_of_secular_set, resid_of_tides_set = self.get_resid_set(point_set, linear_design_mat_set, data_vec_set, model_vec_set)
                print('Residual calculation Done')
                resid_of_tides_point = resid_of_tides_set[self.test_point]
                print("Residual at this point: ", resid_of_tides_point)

                # Calculate the residual per trakc per obs
                residual_analysis_set = self.point_set_residual_analysis(point_set, data_info_set, offsetfields_set, data_vec_set, linear_design_mat_set, model_vec_set)
                print('Residual analysis Done')
                #print(residual_analysis_set)
                #print(residual_analysis_set.keys())
                resid_analysis_point_result = residual_analysis_set[self.test_point]
                print("Residual analysis at this point: ", resid_analysis_point_result)

                # Calculale the model likelihood.
                model_likelihood_set = self.get_model_likelihood_set(point_set, linear_design_mat_set, data_vec_set, model_vec_set, invCd_set)
                print('Model likelihood calculation Done')
                model_likelihood_point = model_likelihood_set[self.test_point]
                print("Model likelihood at this point: ", model_likelihood_point)

                # Convert to tidal params.
                tide_vec_set = self.model_vec_set_to_tide_vec_set(point_set, model_vec_set)
                #print('tide_vec_set: ',tide_vec_set)
                print('Tide vec set Done')
    
                # Convert model posterior to uncertainty of params.
                # Require: tide_vec and Cm_p
                tide_vec_uq_set, secular_corr_set = self.model_posterior_to_uncertainty_set(point_set, tide_vec_set, Cm_p_set)
                self.export_to_others_set_secular_corr(point_set, secular_corr_set, others_set)

                print('Uncertainty set estimation Done')
        
                print('Point set inversion Done')
    
                ############ Some additional work ##############################
                
                # if it is tides_3 and this is a new enumerated grounding_level_int
                if self.task_name == "tides_3" and tides_3_mode == "find_optimal_gl" and (isinstance(grounding_level_int, int) or isinstance(grounding_level_int, dict)):
                    print('Additional work for tides_3 saving the results')
                    # Save the corresponding up_scale and residuals
                    self.export_to_others_set_wrt_gl(point_set, grounding_level_int, model_vec_set, model_likelihood_set, resid_of_tides_set, others_set)

            ## End of enumeration ##

            # Select the optimal grounding level
            # If mode is tides_3 and the enumeration is actually done, so the others set is done
            forceUpdateOthers = False
            if self.task_name == "tides_3" and (tides_3_mode == "find_optimal_gl" or forceUpdateOthers):
                
                # Select the optimal grounding level
                self.select_optimal_grounding_level(point_set, self.grid_set_velo, others_set)
        
                # Show the results at test_point 
                optimal_grounding_level_int = others_set[self.test_point]["optimal_grounding_level"]
                optimal_grounding_level = optimal_grounding_level_int / 10**6

                print("Optimal grounding level before scaling: ", optimal_grounding_level)

                print("####")
                print("optimal gl: ", others_set[self.test_point]['optimal_grounding_level'])
                #print("gl model likelihood: ", others_set[self.test_point]['grounding_level_model_likelihood'])
                #print("gl up scale: ", others_set[self.test_point]['grounding_level_up_scale'])
                #print("gl prob: ", others_set[self.test_point]['grounding_level_prob'])
                print("gl credible interval: ", others_set[self.test_point]['grounding_level_credible_interval'])
                print("####")

                # plot gl marginal dist at test point
                plot_gl_dist = False

                if plot_gl_dist:
                    gls = []
                    gl_probs = [] 
                    for grounding_level_int, gl_prob in sorted(others_set[self.test_point]["grounding_level_prob"].items()):
                        gls.append(grounding_level_int / 10**6)
                        gl_probs.append(gl_prob)

                   
                    #print("sum of probs: ", np.nansum(gl_probs))
                    #print("probs: ", gls, gl_probs)

                    gl_ci = others_set[self.test_point]['grounding_level_credible_interval']

                    fig = plt.figure(1, figsize=(7,7))
                    ax = fig.add_subplot(111)
                    ax.tick_params(axis='both', labelsize=10)
                    ax.plot(gls, gl_probs, "k")
                    ax.plot(gls, gl_probs, "k.")

                    ax.plot([gl_ci[0], gl_ci[0]], [0,max(gl_probs)], "r")
                    ax.plot([gl_ci[1], gl_ci[1]], [0,max(gl_probs)], "r")

                    lowest_tide_height = others_set[point]['lowest_tide_height']
                    ax.plot([lowest_tide_height, lowest_tide_height], [0, max(gl_probs)], "b-")

                    ax.set_xlim([-4, 0])
                    
                    ax.set_ylabel("probability density",fontsize=15)
                    ax.set_xlabel("grounding level",fontsize=15)
                    fig.savefig(self.estimation_dir + "/prob_{}.png".format(self.test_point_str))
                    plt.close(1)

                    # Save the results
                    test_point_gl_dist_pkl = self.estimation_dir + '/dist_{}.pkl'.format(self.test_point_str)
                    gl_dist = {}
                    gl_dist['gls'] = gls
                    gl_dist['gl_probs'] = gl_probs
                    gl_dist['gl_ci'] = gl_ci
                    gl_dist['alpha'] = 0.68
                    gl_dist['lowest_tide'] = lowest_tide_height

                    with open(test_point_gl_dist_pkl, 'wb') as f:
                        pickle.dump(gl_dist, f)

                    #print(stop)

                if not np.isnan(optimal_grounding_level_int):
                    up_scale = others_set[self.test_point]['grounding_level_up_scale'][optimal_grounding_level_int]

                    print("The scaling is: ", up_scale)
                    print("Optimal grounding level after scaling: ", optimal_grounding_level * up_scale)
                else:
                    print("No result (NaN) at test point")

            # Stop the code here for testing
            #print(stop)

            ########### Show the results ########################
            # Stack the true and inverted models.
            # Show on point in the point set.

            self.show_vecs = False
            show_control = False
            if self.single_point_mode:
                show_control = True

            if self.est_topo_resid:
                # The length has problem
                show_control = False
            
            if (self.show_vecs == True or show_control== True) and self.task_name == "tides_1":
   
                if self.test_point in true_tide_vec_set:
                    stacked_vecs = np.hstack((  true_tide_vec_set[self.test_point], 
                                                tide_vec_set[self.test_point], 
                                                tide_vec_uq_set[self.test_point]))
                    row_names = ['Input','Estimated','Uncertainty']
                    column_names = ['Secular'] + self.modeling_tides
                else:
                    stacked_vecs = np.hstack((  tide_vec_set[self.test_point], 
                                                tide_vec_uq_set[self.test_point]))

                    row_names = ['Estimated','Uncertainty']
                    column_names = ['Secular'] + self.modeling_tides
   
                if not np.isnan(tide_vec_set[self.test_point][0,0]): 
                    self.display.display_vecs(stacked_vecs, row_names, column_names, test_id)
                else:
                    print("No valid estimation")

            #######################################################

        # Non-linear model 
        if task_name == "tides_2" and inversion_method in ['Bayesian_MCMC', 'Nonlinear_Optimization']:

            ## Step 1: Prepare the solver (named BMC)
            BMC = solvers(self.param_file)
            
            # Set the point_set to work on
            BMC.set_point_set(point_set)

            # Find the linear design mat
            linear_design_mat_set = self.build_G_set(point_set, offsetfields_set=offsetfields_set)

            # Set linear tides
            BMC.set_linear_design_mat_set(linear_design_mat_set)

            # Set modeling tides
            BMC.set_modeling_tides(self.modeling_tides)
            
            # Provide model priors
            self.up_lower = -4
            self.up_upper = 0
            BMC.set_model_priors(model_mean_prior_set = true_tide_vec_set, no_secular_up = self.no_secular_up, up_short_period = self.up_short_period, horizontal_long_period = self.horizontal_long_period, up_lower = self.up_lower, up_upper = self.up_upper)

            # Provide data priors
            BMC.set_noise_sigma_set(noise_sigma_set)

            # Provide data
            BMC.set_data_set(data_vec_set)

            # Provide offsetfield info
            BMC.set_offsetfields_set(offsetfields_set)

            # Stack the design matrix modeling tides
            stack_design_mat_set = self.get_stack_design_mat_set(point_set, self.model_design_mat_set, offsetfields_set)

            # Provid the matrix to simulator
            BMC.set_stack_design_mat_set(stack_design_mat_set)

            # Obtain the up displacement
            up_disp_set = self.get_up_disp_set(point_set, offsetfields_set)

            # Provide the up displacement to the solver
            BMC.set_up_disp_set(up_disp_set)

            # Obtain true model vec from true tide vec
            if self.simulation_mode:
                true_model_vec_set = self.tide_vec_set_to_model_vec_set(point_set, true_tide_vec_set)
            else:
                true_model_vec_set = None

            BMC.set_true_model_vec_set(true_model_vec_set)

            # Pass the velo model to solver as well, as it contains the up_scale
            BMC.set_grid_set_velo(self.grid_set_velo)

            # Set task name
            BMC.set_task_name(task_name)

            # Run inversion
            est_grounding = None
            suffix = str(data_mode['csk'])+'_' + str(data_mode['s1'])

            if inversion_method=="Bayesian_MCMC":
                # single-point mode
                model_vec, est_grounding = BMC.run_MCMC(run_point = self.test_point, suffix = suffix)
                print("*** Result of Bayesian MCMC")
                print(model_vec)
            
            elif inversion_method=="Nonlinear_Optimization":
                # calls scipy.optimize for direct nonlinear optimzation
                # point-set mode
                optimize_result = BMC.run_optimize(run_point = self.test_point)
                model_vec_set, grounding_set, up_scale_set = optimize_result

                # convert to tidal params
                tide_vec_set = self.model_vec_set_to_tide_vec_set(point_set, model_vec_set)

                # put true and estimated grounding and up_scale into others_set
                # true value is in self.grid_set_velo and self.simulation_grounding_level
                self.extract_grounding_up_scale_set(point_set, grounding_set, up_scale_set, others_set)

                # get results of test_point
                model_vec = model_vec_set[self.test_point]
                est_grounding = grounding_set[self.test_point]
                up_scale = up_scale_set[self.test_point]
                
                print("*** Result of nonlinear optimization at test point")
                print("model_vec: ", model_vec)
                print("grounding: ", est_grounding)
                print("up scale: ", up_scale)
            else:
                raise Exception()

            #######################################
            ###  Compare model vec and tide_vec on test_point ###
            stacked_model_vecs = []
            stacked_tide_vecs = []
            row_names = []

            # True model
            if true_model_vec_set is not None:
                true_model_vec = true_model_vec_set[self.test_point]
                true_tide_vec = true_tide_vec_set[self.test_point]

                stacked_model_vecs.append(true_model_vec)
                stacked_tide_vecs.append(true_tide_vec)
                row_names.append("Input")

            # Linear model
            #if bl_model_vec.shape[0]>1:
            #    bl_tide_vec = self.model_vec_to_tide_vec(bl_model_vec)

            #    stacked_model_vecs.append(bl_model_vec)
            #    stacked_tide_vecs.append(bl_tide_vec)
            #    row_names.append("Linear")

            # Non-linear model
            tide_vec = self.model_vec_to_tide_vec(model_vec)

            stacked_model_vecs.append(model_vec)
            stacked_tide_vecs.append(tide_vec)
            row_names.append("Nonlinear")

            print("Compare model vecs")
            stacked_model_vecs = np.hstack(stacked_model_vecs)
            print(stacked_model_vecs)

            print("Compare tide vec")
            stacked_tide_vecs = np.hstack((stacked_tide_vecs))
            print(stacked_tide_vecs)

            print("@@ Estimated grounding level @@", est_grounding)

            # Visualize the models in a table
            stacked_vecs = stacked_tide_vecs
            column_names = ['Secular'] + self.modeling_tides
            self.display.display_vecs(stacked_vecs, row_names,column_names, test_id)

        ########### Inversion done ##########################
        # Record and return
        print("Recording...")
        all_sets = {}
        all_sets['true_tide_vec_set'] =  true_tide_vec_set
        all_sets['tide_vec_set'] = tide_vec_set

        all_sets['tide_vec_uq_set'] = tide_vec_uq_set
        all_sets['resid_of_secular_set'] = resid_of_secular_set
        all_sets['resid_of_tides_set'] = resid_of_tides_set
        all_sets['others_set'] = others_set

        all_sets['residual_analysis_set'] = residual_analysis_set

        return all_sets

