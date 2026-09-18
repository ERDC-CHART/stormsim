    # ------------ COMMENTS
    # Structure type defines set of equations to use & emperical coefficients used
    # Additionally, Eurotop guidance uses seaward slope as an additional decision point
    # for equation definition
    # Equations are from http://www.overtopping-manual.com/assets/downloads/EurOtop_II_2018_Final_version.pdf


    #        From Abi:
    #            If there is a foreshore influence: no significant mound is considered,non-
    #            impulsive is assumed, and no composite structures are considered.
    #           Does not include battered wall types
    #            Emergent toe of wall is considered a wall on embankment
    #            Cr value is not considered for armored crests. See EurOtop Eq 6.8 for info.
    #            Assume no berm influence
    #            Assume shore normal wave

    # -------------- IMPORT LIBRARIES
import numpy as np
import numbers

class runup_and_ot_eurotop_2018:

    def __init__(self,args,rng=None):
        # Generator for the EurOtop 5.18 coefficient uncertainty. Callers pass
        # a seeded one to make a run reproducible; the default draws from
        # entropy, as this class always did.
        self.rng = rng if rng is not None else np.random.default_rng()
        # ------ INITIAL DATA PREP -----
        # Define Structure Type
        self.structure_type = args['type'] # 1 = sloping sea dike & embankment seawall, 2 - armoured rubble slopes and mounds, 3 - vertical, battered or steep walls
        # Define Application Context
        self.app_type = args['app_type'] # 1 = Mean Value Approach, 2 = Design or Assesment Approach
        # Define Structure Material (For Roughness Influence Factor)
        self.structure_material = args['material'] # grass, concrete, basalt
        # Define Structure Crest Elevation
        self.structure_crest_elevation = args['crest_elevation']
        # Define Structure Toe Elevation
        self.structure_toe_elevation = args['toe_elevation']
        # Define Structure Slope
        self.structure_seaward_slope = args['seaward_slope']
        # Define Structure Slope
        self.structure_crest_width = args['crest_width']
        # Ensure that these attributes are NumPy arrays
        self.forcing_SWL = np.asarray(args['SWL'])
        self.forcing_Hm0 = np.asarray(args['Hm0'])
        self.forcing_Tm10 = np.asarray(args['Tm10'])
        # Validate the lengths
        if not (np.shape(self.forcing_SWL) == np.shape(self.forcing_Hm0) == np.shape(self.forcing_Tm10)):
            raise ValueError("SWL, Hm0, and Tm10 must be arrays of the same length.")
        # Compute FreeBoard
        self.structure_freeboard = self.structure_crest_elevation - self.forcing_SWL
        # Define Gravity Constant
        self.gravity_constant = 9.81

        # --------- DEFINE INFLUENCE FACTORS DEFAULTS ----------
        # Berm Influence Factor
        self.ifactors_gamma_b = 1
        # Wave Obliqueness Runup Influence Factor
        self.ifactors_gamma_beta_runup = 1
        # Wave Obliqueness Overtopping Influence Factor
        self.ifactors_gamma_beta_overtoping = 1

    # Helper Function For Custom Value Roughness Influence Factor
    def _is_numeric(self, x):
        return (
            isinstance(x, numbers.Number)
            or isinstance(x, np.number)
            or (isinstance(x, np.ndarray) and np.issubdtype(x.dtype, np.number))
        )

    # ---------- DEFINE INFLUENCE FACTORS ---------
    # Roughness Influence Factor
    def _roughness_influence_factor(self):
        # Initialize gamma_f based on the material
        if self._is_numeric(self.structure_material):
            gamma_f = self.structure_material
        elif self.structure_material == 'grass':
            gamma_f = np.where(self.forcing_Hm0 < 0.75,
                                1.15 * np.sqrt(self.forcing_Hm0),
                                1)

        elif self.structure_material == 'concrete':
            gamma_f = np.ones_like(self.forcing_Hm0)

        elif self.structure_material == 'basalt':
            gamma_f = 0.9 * np.ones_like(self.forcing_Hm0)

        else:
            print('Unsupported material. Please use grass, concrete or basalt. Assuming concrete material.')
            self.structure_material = 'concrete'
            gamma_f = np.ones_like(self.forcing_Hm0)

        # Store the result
        self.ifactors_gamma_f = gamma_f

    # Wall Influence Factor
    def _wall_influence_factor(self):
        ### Wall Influence Coefficient
        if self.structure_type == 3: # vertical, battered or steep walls
            # Compute Wall Height
            wall_height = self.structure_crest_elevation - self.structure_toe_elevation
            # Compute Wall Influence Factor (Gamma_v)
            gamma_v = np.exp(-0.56*wall_height/self.structure_freeboard)
            # Compute gamma_star
            gamma_star = gamma_v
        elif self.structure_type == 1 or self.structure_type == 2:
            # Factor Not Applicable - Set gamma_v as 1
            gamma_v = 1
            # Factor Not Applicable - Set gamma_star as 1
            gamma_star = gamma_v
        else:
            print('Unsupported structure type. Please use levee, floodwall, or rubblemound.')
            gamma_v = 1

        # return Variables
        self.ifactors_gamma_v = gamma_v
        self.ifactors_gamma_star = gamma_star
    # Wave obliquity Inlfuence Factor
    def wave_obliquity_influence_factor(self):
        ### Wave Obliquity Coefficient
        # Still Not Implemented (Ch 5.4.4)
        # Runup & overtoppping gamma_beta are different
        self.ifactors_gamma_beta_runup = 1
        self.ifactors_gamma_beta_overtoping = 1
        raise NotImplementedError()
    # Berm Influence Factor
    def berm_influence_factor(self):
        ### Berm Influence Factor
        # Still Not Implemented ()
        self.ifactors_gamma_b = 1
        raise NotImplementedError()

    # Negative Freeboard Influence Factor
    def _negative_freeboard_influence_factor(self):
        ### NEgative Freeboard Influence Factor
        self.ifactors_q_overflow = np.where(self.structure_freeboard < 0,
                                            0.54 * np.sqrt(self.gravity_constant * np.abs(self.structure_freeboard)),
                                            0)
        self.ifactors_Rc_corrt = np.where(self.structure_freeboard < 0, 0, self.structure_freeboard)


    # ---------- EQUATION COEFFICIENTS ---------
    # Define Equation Coefficients
    def _coefficients_setup(self):
        if self.app_type  == 1: # Mean Value Approach
            # Define Runup Coefficiets
            self.c1_runup = 1.65 # EurOtop Eq 5.1
            self.c2_runup = 1.00 # EurOtop Eq 5.2
            self.c3_runup = 0.80 # EurOtop Eq 5.6
            # Define Overtopping Coefficients
            self.c1_ot = 0.023   # EurOtop Eq 5.10
            self.c2_ot = 2.700   # EurOtop Eq 5.10
            self.c3_ot = 0.090   # EurOtop Eq 5.11
            self.c4_ot = 1.500   # EurOtop Eq 5.11

            if self.structure_type == 3: # Vertical, Battered or Steep walls
                # Vertical wall coefficients
                self.c1_wall_ot = 0.047 # EurOtop Eq 7.1
                self.c2_wall_ot = 2.350 # EurOtop Eq 7.1
                self.c3_wall_ot = 0.050 # EurOtop Eq 7.5
                self.c4_wall_ot = 2.780 # EurOtop Eq 7.5
                self.c5_wall_ot = 0.011 # EurOtop Eq 7.7 and 7.15
                self.c6_wall_ot = 0.0014 # EurOtop Eq 7.8 and 7.14


        elif self.app_type  == 2 : # Design or Assesment Approach
            # Define Runup Coefficiets
            self.c1_runup = 1.75 # EurOtop Eq 5.4
            self.c2_runup = 1.07 # EurOtop Eq 5.5
            self.c3_runup = 0.86 # EurOtop Eq 5.7
            # Define Overtopping Coefficients
            self.c1_ot = 0.026   # EurOtop Eq 5.12
            self.c2_ot = 2.500   # EurOtop Eq 5.12
            self.c3_ot = 0.1035   # EurOtop Eq 5.13
            self.c4_ot = 1.35   # EurOtop Eq 5.13

            if self.structure_type == 3: # Vertical, Battered or Steep walls
                # Vertical wall coefficients (Needs To be Changed)
                self.c1_wall_ot = 0.047 # EurOtop Eq 7.1
                self.c2_wall_ot = 2.350 # EurOtop Eq 7.1
                self.c3_wall_ot = 0.050 # EurOtop Eq 7.5
                self.c4_wall_ot = 2.780 # EurOtop Eq 7.5
                self.c5_wall_ot = 0.011 # EurOtop Eq 7.7 and 7.15
                self.c6_wall_ot = 0.0014 # EurOtop Eq 7.8 and 7.14

    # ---------- STRUCTURE RESPONSES ---------
    # R2% & OT Gentle Slope Structure Type 1
    def _gentle_slope_levee_response(self):
        # Setup Equation Coefficients
        self._coefficients_setup()
        # Apply Negative Freeboard Influence Factor
        self._negative_freeboard_influence_factor()
        # Apply Wall Influence Factor
        self._wall_influence_factor()
        # Apply Roughness Influence Factor
        self._roughness_influence_factor()

        # Compute Additional Variables
        L_m10 = (self.gravity_constant * self.forcing_Tm10**2) / (2 * np.pi)  # Zero moment wave length
        s_m10 = self.forcing_Hm0 / L_m10  # Wave steepness
        breaker_m10 = (1 / self.structure_seaward_slope) / np.sqrt(s_m10)  # Breaker parameter

        # Compute Run-up and Overtopping
        # ---- RUN-UP ----------------
        R2p_a = self.forcing_Hm0 * self.c1_runup * self.ifactors_gamma_b * self.ifactors_gamma_f * self.ifactors_gamma_beta_runup * breaker_m10
        R2p_max = self.forcing_Hm0 * self.c2_runup * self.ifactors_gamma_f * self.ifactors_gamma_beta_runup * (4 - 1.5 / np.sqrt(self.ifactors_gamma_b * breaker_m10))

        # Negative R2p_max Failsafe
        self.R2p = np.nanmin(np.array([R2p_a, R2p_max]), axis=0)

        # ------- OVERTOPPING -----------
        q_a_term_1 = np.sqrt(self.gravity_constant * self.forcing_Hm0**3)
        q_a_term_2 = (self.c1_ot / np.sqrt(1 / self.structure_seaward_slope)) * self.ifactors_gamma_b * breaker_m10
        q_a_term_3 = np.exp(-(self.c2_ot * self.ifactors_Rc_corrt / breaker_m10 / self.forcing_Hm0 / self.ifactors_gamma_b / self.ifactors_gamma_f / self.ifactors_gamma_beta_overtoping / self.ifactors_gamma_v)**1.3)
        q_a = q_a_term_1 * q_a_term_2 * q_a_term_3

        q_max_term_1 = np.sqrt(self.gravity_constant * self.forcing_Hm0**3) * self.c3_ot
        q_max_term_2 = np.exp(-(self.c4_ot * self.ifactors_Rc_corrt / (self.forcing_Hm0 * self.ifactors_gamma_f * self.ifactors_gamma_beta_overtoping * self.ifactors_gamma_star))**1.3)
        q_max = q_max_term_1 * q_max_term_2

        # Get Minimum
        q = np.nanmin(np.array([q_max, q_a]), axis=0)

        # Apply Negative Freeboard Influence Factor
        self.q = (self.ifactors_q_overflow + q)

    # R2% & OT Steep Slope Structure Type 1
    def _steep_slope_levee_response(self):
        # Setup Equation Coefficients
        # Setup Equation Coefficients
        self._coefficients_setup()
        # Apply Negative Freeboard Influence Factor
        self._negative_freeboard_influence_factor()
        # Apply Wall Influence Factor
        self._wall_influence_factor()
        # Apply Roughness Influence Factor
        self._roughness_influence_factor()
        # Compute Additional Variables
        L_m10 = (self.gravity_constant*self.forcing_Tm10**2)/(2*np.pi)  # Zero moment wave length
        s_m10 = self.forcing_Hm0/L_m10; # Wave steepness
        breaker_m10 = (1/self.structure_seaward_slope)/np.sqrt(s_m10)  # Breaker parameter

        # Rename Influence Factors For Simplicity (g-> gamma)
        g_beta_ot = self.ifactors_gamma_beta_overtoping # Wave Obliqueness Overtopping Influence Factor

        # Random Uncertainty
        randn = self.rng.standard_normal()

        # EurOtop Runup Eq 5.6
        R2p_a = np.nanmin([self.forcing_Hm0*self.c3_runup/(1/self.structure_seaward_slope) + 1.6 , (3*self.forcing_Hm0)], axis=0)
        self.R2p = np.nanmax([np.zeros_like(R2p_a) ,np.nanmax([R2p_a,(1.8*self.forcing_Hm0)], axis=0)], axis= 0)

        # EurOtop Overtopping eq 5.18- assumes only smooth slopes
        a_a = (0.09 - 0.01*(2-self.structure_seaward_slope)**2.1)
        a = a_a+(a_a*0.15*randn)
        b_a = np.nanmin([(1.5+0.42*(2-self.structure_seaward_slope)**1.5),2.35], axis=0)
        b = b_a+(b_a*0.10*randn)
        q = np.sqrt(self.gravity_constant*self.forcing_Hm0**3)*a*np.exp(-(b*self.ifactors_Rc_corrt/(self.forcing_Hm0*g_beta_ot))**1.3)

        self.q = (self.ifactors_q_overflow + q)


    # OT Structure Type 3
    def _overtopping_floodwall(self):
        # Setup Equation Coefficients
        self._coefficients_setup()
        # Apply Negative Freeboard Influence Factor
        self._negative_freeboard_influence_factor()
        # Apply Wall Influence Factor
        self._wall_influence_factor()
        # Apply Roughness Influence Factor
        self._roughness_influence_factor()
        # Wave Obliqueness Overtopping Influence Factor
        g_beta_ot = self.ifactors_gamma_beta_overtoping
        # Sumberged depth of wall
        w_depth=-self.structure_toe_elevation+self.forcing_SWL;
        # depth above toe mound/berm in front of vertical wall
        d_wall = self.ifactors_Rc_corrt- w_depth;
        # Water Depth Ratio
        w_depth_ratio = w_depth/self.forcing_Hm0
        # no foreshore influence
        # EurOtop Overtopping Eq 7.1
        q_no_foreshore = np.sqrt(self.gravity_constant*self.forcing_Hm0**3)*self.c1_wall_ot*np.exp(-((self.c2_wall_ot/g_beta_ot)*self.ifactors_Rc_corrt/self.forcing_Hm0)**1.3)
        # foreshore influence
        q_foreshore  = np.sqrt(self.gravity_constant*self.forcing_Hm0**3)*self.c3_wall_ot*np.exp(-(self.c4_wall_ot/g_beta_ot)*self.ifactors_Rc_corrt/self.forcing_Hm0)
        # Select between the two cases based on w_depth_ratio using np.where
        q = np.where(w_depth_ratio > 4, q_no_foreshore, q_foreshore)
        # Append To Outputs
        self.q = q + self.ifactors_q_overflow
        self.R2p = np.zeros_like(self.q)

    # ---------- EXECUTION FUNCTION ---------
    def structure_response(self):
        # Call Corresponding Function Based On Structure Type
        if self.structure_type == 1: # sloping sea dike & embankment seawall
            # Compute Structure Responses
            if (self.structure_seaward_slope>=2) & (self.structure_seaward_slope<=9.99): # "(Relatively) Gentle Slope"
                # Call Structure Response
                self._gentle_slope_levee_response()
            elif (self.structure_seaward_slope>0.1) & (self.structure_seaward_slope<2): # "(Very) Steep Slope"
                # Call Structure Response
                self._steep_slope_levee_response()

        elif self.structure_type == 2: # 2 - armoured rubble slopes and mounds
            if self.structure_seaward_slope>2:
                pass
            elif self.structure_seaward_slope<2:
                pass

        elif self.structure_type == 3: # 3 - vertical, battered or steep walls
            self._overtopping_floodwall()
