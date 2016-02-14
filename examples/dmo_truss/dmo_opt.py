# Import this for directory creation
import os

# Import the greatest common divisor code
from fractions import gcd

# Import MPI 
import mpi4py.MPI as MPI

# Import ParOpt
from paropt import ParOpt

# Import argparse
import argparse

# Import numpy
import numpy as np

# Import the truss analysis problem
from dmo_truss_analysis import TrussAnalysis

def get_ground_structure(N=4, M=4, L=2.5, P=10.0, n=10):
    '''
    Set up the connectivity for a ground structure consisting of a 2D
    mesh of (N x M) nodes of completely connected elements.

    A single point load is applied at the lower right-hand-side of the
    mesh with a value of P. All nodes are evenly spaced at a distance
    L.

    input:
    N:  number of nodes in the x-direction
    M:  number of nodes in the y-direction
    L:  distance between nodes

    returns
    conn:   the connectivity
    xpos:   the nodal locations
    loads:  the loading conditions applied to the problem
    P:      the load applied to the mesh
    '''

    # First, generate a co-prime grid that will be used to 
    grid = []
    for x in range(1,n+1):
        for y in range(1,n+1):
            if gcd(x, y) == 1:
                grid.append((x,y))

    # Reflect the ge
    reflect = []
    for d in grid:
        reflect.append((-d[0], d[1]))

    grid.extend(reflect)
    grid.extend([(0,1), (1,0)])

    # Set up the connectivity array
    conn = []
    for i in xrange(N):
        for j in xrange(M):
            n1 = i + N*j
            for d in grid:
                if ((i + d[0] < N) and (j + d[1] < M) and
                    (i + d[0] >= 0) and (j + d[1] >= 0)):
                    n2 = i + d[0] + (j + d[1])*N
                    conn.append([n1, n2])

    # Set the positions of all the nodes
    xpos = []
    for j in xrange(M):
        for i in xrange(N):
            xpos.extend([i*L, j*L])

    # Set the node locations
    loads = {}
    loads[N-1] = [0, -P]

    bcs = {}
    for j in xrange(M):
        bcs[j*N] = [0, 1]

    return conn, xpos, loads, bcs

def setup_ground_struct(N, M, L=2.5, E=70e9, 
                        t_min=1e-2, sigma=100.0,
                        use_mass_constraint=False):
    '''
    Create a ground structure with a given number of nodes and
    material properties.
    '''

    # Set the values for the
    Avals = [ 0.01, 0.02, 0.05 ]
    rho = [ 25.0, 54.0, 150.0 ]

    # Create the ground structure
    conn, xpos, loads, bcs = get_ground_structure(N=N, M=M, 
                                                  L=L, P=10e3)

    # Set the scaling for the material variables
    Area_scale = 1.0

    # Set the fixed mass constraint
    AR = 1.0*(N-1)/(M-1)
    m_fixed = (M-1)*(N-1)*L*rho[-1]

    # Create the truss topology optimization object
    truss = TrussAnalysis(conn, xpos, loads, bcs, 
                          E, rho, Avals, m_fixed, 
                          t_min=t_min, sigma=sigma, 
                          use_mass_constraint=use_mass_constraint)

    # Set the options
    truss.setInequalityOptions(dense_ineq=True, 
                               sparse_ineq=False,
                               use_lower=True,
                               use_upper=True)

    return truss

def paropt_truss(truss, use_hessian=False,
                 max_qn_subspace=50, qn_type=ParOpt.BFGS):
    '''
    Optimize the given truss structure using ParOpt
    '''

    # Create the optimizer
    opt = ParOpt.pyParOpt(truss, max_qn_subspace, qn_type)

    # Set the optimality tolerance
    opt.setAbsOptimalityTol(1e-5)

    # Set the Hessian-vector product iterations
    if use_hessian:
        opt.setUseLineSearch(0)
        opt.setUseHvecProduct(1)
        opt.setGMRESSubspaceSize(100)
        opt.setNKSwitchTolerance(1.0)
        opt.setEisenstatWalkerParameters(0.5, 0.0)
        opt.setGMRESTolerances(1.0, 1e-30)
    else:
        opt.setUseHvecProduct(0)

    # Set optimization parameters
    opt.setArmijioParam(1e-5)
    opt.setMaxMajorIterations(2500)

    # Perform a quick check of the gradient (and Hessian)
    opt.checkGradients(1e-6)

    return opt

def optimize_truss(N, M, heuristic, root_dir='results',
                   use_mass_constraint=False, sigma=100.0,
                   t_min_init=0.125, max_d=1e-5, theta=1e-2):
    # Optimize the structure
    prefix = os.path.join(root_dir, '%dx%d'%(N, M), heuristic)

    # Make sure that the directory exists
    if not os.path.exists(prefix):
        os.makedirs(prefix)
   
    # Create the ground structure and optimization
    truss = setup_ground_struct(N, M, sigma=sigma,
                                use_mass_constraint=use_mass_constraint,
                                t_min=t_min_init)
    
    # Set up the optimization problem in ParOpt
    opt = paropt_truss(truss, use_hessian=use_hessian,
                       qn_type=ParOpt.BFGS)

    # Create a vector of all ones
    m_add = 0.0
    if use_mass_constraint:
        xones = np.ones(truss.gmass.shape)
        m_add = truss.getMass(xones)/truss.nmats
    
    # Keep track of the fixed mass
    m_fixed_init = 1.0*truss.m_fixed
    truss.m_fixed = m_fixed_init + truss.t_min*m_add

    # Log the optimization file
    log_filename = os.path.join(prefix, 'log_file.dat')
    fp = open(log_filename, 'w')

    # Write the header out to the file
    s = 'Variables = iteration, "min SE", "max SE", "fobj", '
    s += '"min gamma", "max gamma", "gamma", '
    s += '"min d", "max d", "tau", "mass infeas", '
    s += 'feval, geval, hvec, time\n'
    s += 'Zone T = %s\n'%(heuristic)
    fp.write(s)

    # Keep track of the ellapsed CPU time
    init_time = MPI.Wtime()

    # Initialize the gamma values
    gamma_init = 1e-4
    gamma = np.zeros(truss.nelems)

    # Set the heuristic parameters
    alpha = 1.25
    beta = 0.25
    print 'Heuristic: %s  alpha = %8.4f beta = %8.4f'%(
        heuristic, alpha, beta)

    # Previous value of the objective function
    fobj_prev = 0.0

    # Keep track of the objective/tau the last time
    # the penalty parameters were incremented
    fobj_iter = 0.0
    tau_iter = 0.0

    # Keep track of the number of iterations
    niters = 0
    for k in xrange(150):
        # Set the output file to use
        fname = os.path.join(prefix, 'truss_paropt_iter%d.out'%(k)) 
        opt.setOutputFile(fname)

        # Optimize the truss
        if k > 0:
            opt.setInitBarrierParameter(1e-4)
        opt.optimize()

        # Get the optimized point
        x = opt.getOptimizedPoint()

        # Get the discrete infeasibility measure
        d = truss.getDiscreteInfeas(x)

        # Get the strain energy associated with each element
        Ue = truss.getStrainEnergy(x)

        # Compute the infeasibility of the mass constraint
        m_infeas = max(truss.getMass(x)/truss.m_fixed - 1.0, 0.0)

        # Compute the objective function
        fobj = np.sum(Ue)

        # Compute the discrete infeasibility measure
        tau = np.sum(d)

        # Print out the iteration information to the screen
        print 'Iteration %d'%(k)
        print 'Min/max SE:    %15.5e %15.5e  Total: %15.5e'%(
            np.min(Ue), np.max(Ue), np.sum(Ue))
        print 'Min/max gamma: %15.5e %15.5e  Total: %15.5e'%(
            np.min(gamma), np.max(gamma), np.sum(gamma))
        print 'Min/max d:     %15.5e %15.5e  Total: %15.5e'%(
            np.min(d), np.max(d), np.sum(d))
        print 'Mass infeas:   %15.5e'%(m_infeas)
        print 'min(t):        %15.5e'%(truss.t_min)

        s = '%d %e %e %e %e %e %e %e %e %e %e '%(
            k, np.min(Ue), np.max(Ue), np.sum(Ue),
            np.min(gamma), np.max(gamma), np.sum(gamma),
            np.min(d), np.max(d), np.sum(d), m_infeas)
        s += '%d %d %d %e\n'%(
            truss.fevals, truss.gevals, truss.hevals, 
            MPI.Wtime() - init_time)
        fp.write(s)
        fp.flush()

        # Terminate if the maximum discrete infeasibility measure is
        # sufficiently low
        if np.max(d) < max_d:
            break

        # Print the output
        filename = 'opt_truss_iter%d.tex'%(k)
        output = os.path.join(prefix, filename)
        truss.printTruss(x, filename=output)

        if k == 0:
            tau_iter = 1.0*tau
            fobj_iter = 1.0*fobj
            gamma[:] = gamma_init
        elif abs((fobj - fobj_prev)/fobj < 0.001):
            # Normalize the coefficients
            y = Ue/np.max(Ue)
            z = d/np.max(d)

            # Compute the new coefficients based on the scheme
            if heuristic == 'scalar':
                gamma *= alpha + beta
            elif heuristic == 'linear':
                gamma *= alpha + beta*y
            elif heuristic == 'discrete':
                gamma *= alpha + beta*z
            elif heuristic == 'inverse':
                gamma *= alpha + beta*z*(1.0 - y)/(1.0 + 2*y)

            # Adjust the coefficients so they satisfy the convergence
            # property
            gmax = max(gamma)
            for i in xrange(len(gamma)):
                gamma[i] = max(gamma[i], theta*gmax)

            # Set the new value of t_min
            truss.t_min = 0.0 # max(0.0, truss.t_min - 0.1*t_min_init)
            truss.m_fixed = m_fixed_init + max(0.0, truss.t_min*m_add)
    
        # Set the new penalty
        truss.setNewInitPointPenalty(x, gamma)

        # Store the previous value of the objective function
        fobj_prev = 1.0*fobj

        # Increase the iteration counter
        niters += 1

    # Close the file
    fp.close()

    # PDFLatex all the output files
    for k in xrange(niters):
        filename = 'opt_truss_iter%d.tex'%(k)
        os.system('cd %s; pdflatex %s > /dev/null ; cd ..;'%(
            prefix, filename))
    
    # Print out the last optimized truss
    filename = 'opt_truss.tex'
    output = os.path.join(prefix, filename)
    truss.printTruss(x, filename=output)
    os.system('cd %s; pdflatex %s > /dev/null ; cd ..;'%(prefix, filename))

    return

# Parse the command line arguments 
parser = argparse.ArgumentParser()
parser.add_argument('--N', type=int, default=4, 
                    help='Nodes in x-direction')
parser.add_argument('--M', type=int, default=3, 
                    help='Nodes in y-direction')
parser.add_argument('--profile', action='store_true', 
                    default=False, help='Performance profile')
parser.add_argument('--heuristic', type=str, default='scalar',
                    help='Heuristic type')
parser.add_argument('--use_mass_constraint', action='store_true',
                    default=False, help='Use the mass constraint')
parser.add_argument('--sigma', type=float, default=100.0,
                    help='Penalty parameter value')
args = parser.parse_args()

# Get the arguments
N = args.N
M = args.M
profile = args.profile
heuristic = args.heuristic
use_mass_constraint = args.use_mass_constraint
sigma = args.sigma

# Set the root results directory
root_dir = 'results'
if use_mass_constraint:
    root_dir = 'con-results'

# Always use the Hessian-vector product implementation
use_hessian = True

# The trusses used in this instance
trusses = [ (3, 3), (4, 3), (5, 3), (6, 3),
            (4, 4), (5, 4), (6, 4), (7, 4), (8, 4), (9, 4), (10, 4),
            (5, 5), (6, 5), (7, 5), (8, 5), (9, 5), (10, 5),
            (6, 6), (7, 6), (8, 6), (9, 6), (10, 6) ]

# Run either the optimizations or the
if profile:
    for N, M in trusses:
        try:
            optimize_truss(N, M, heuristic, root_dir=root_dir,
                           use_mass_constraint=use_mass_constraint,
                           sigma=sigma)
        except:
            pass
else:
    optimize_truss(N, M, heuristic, root_dir=root_dir,
                   use_mass_constraint=use_mass_constraint,
                   sigma=sigma)
