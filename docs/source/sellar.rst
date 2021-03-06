Sellar problem
==============

To illustrate the application of ParOpt, consider the following optimization problem with the Sellar objective function:

.. math::

    \begin{align}
        \text{min} \qquad & x_1 + x_2^2 + x_3 + e^{-x_4} \\
        \text{with respect to} \qquad & 0 \le x_{1} \le 10 \\
        &  0 \le x_{2} \le 10 \\
        & -1 \le x_{3} \le 3.16 \\
        & -1 \le x_{4} \le 24 \\
        \text{subject to} \qquad & x_{1} + x_{2} - 1 \ge 0 \\
    \end{align}

C++ implementation
------------------

The first step to use the ParOpt optimization library is to create a problem class which inherits from ParOptProblem.
This class is used by ParOpt's interior-point or trust-region algorithms to get the function and gradient values from the problem.

Key functions required for the implementation of a ParOptProblem class are described below.

.. code-block:: c++

      void getVarsAndBounds( ParOptVec *xvec,
                             ParOptVec *lbvec, ParOptVec *ubvec );

To begin the optimization problem, the optimizer must know the starting point and the variable bounds for the problem
The member function getVarsAndBounds retrieves this information.
On return, the initial design variables are written to the design vector x, and the lower and upper bounds are written to the vectors lb and ub, respectively.

.. code-block:: c++

      int evalObjCon( ParOptVec *xvec,
                      ParOptScalar *fobj, ParOptScalar *cons );
      int evalObjConGradient( ParOptVec *xvec,
                              ParOptVec *gvec, ParOptVec **Ac );

The class inheriting from ParOptProblem must also implement member functions to evaluate the objective and constraints and their gradients.
The function evalObjCon takes in the design vector x, and returns a scalar value in fobj, and an array of the dense constraint values in cons.
When the code is run in parallel, the same objective value and constraint values must be returned on all processors.
The function evalObjConGradient sets the values of the objective and constraint gradients into the vector gvec, and the array of vectors Ac, respectively.
If an error is encountered during the evaluation of either the functions or gradients, a non-zero error code should be returned to terminate the optimization.

When implemented in C++, the complete Sellar problem is:

.. code-block:: c++

    #include "ParOptInteriorPoint.h"

    /*
      The following is a simple implementation of a Sellar function with
      constraints that can be used to test the parallel optimizer.
    */
    class Sellar : public ParOptProblem {
    public:
      static const int nvars = 4;
      static const int ncon = 1;
      Sellar( MPI_Comm _comm ): ParOptProblem(_comm, nvars, ncon, 0, 0){}

      //! Get the variables/bounds
      void getVarsAndBounds( ParOptVec *xvec,
                             ParOptVec *lbvec,
                             ParOptVec *ubvec ){
        // declare design variable and bounds vector
        ParOptScalar *x, *lb, *ub;

        // store the memory addresses of the class variables
        xvec->getArray(&x);
        lbvec->getArray(&lb);
        ubvec->getArray(&ub);

        // Set the initial design variables
        x[0] = 2.0;
        x[1] = 1.0;
        x[2] = 0.0;
        x[3] = 0.0;
        
        // set lower and upper bounds to design variables
        lb[0] = 0.0;  lb[1]  = 0.0; lb[2] = -1.0; lb[3] = -1.0;
        ub[0] = 10.0; ub[1] = 10.0; ub[2] = 3.16; ub[3] = 24.0; 
      }
      
      //! Evaluate the objective and constraints
      int evalObjCon( ParOptVec *xvec,
                      ParOptScalar *fobj, ParOptScalar *cons ){

        // declare local variables
        ParOptScalar *x;
        xvec->getArray(&x);

        // the objective function
        *fobj = x[1]*x[1] + x[0] + x[2] + exp(-x[3]);
        cons[0] = x[0] + x[1] - 1.0;

        return 0;
      }
      
      //! Evaluate the objective and constraint gradients
      int evalObjConGradient( ParOptVec *xvec, ParOptVec *gvec, ParOptVec **Ac ){

        // define the local variables
        double *x, *g;

        // get the local variables values
        xvec->getArray(&x);

        // derivative of the objective function wrt to the DV
        gvec->zeroEntries();
        gvec->getArray(&g);
        g[0] = 1.0;
        g[1] = 2.0*x[1];
        g[2] = 1.0;
        g[3] = -exp(-x[3]);

        // Derivative of the constraint
        Ac[0]->zeroEntries();
        Ac[0]->getArray(&g);
        g[0] = 1.0;
        g[1] = 1.0;
        
        return 0;
      }
    };

    int main( int argc, char* argv[] ){
      MPI_Init(&argc, &argv);

      // Allocate the Sellar function
      Sellar *sellar = new Sellar(MPI_COMM_SELF);
      sellar->incref();
      
      // Allocate the optimizer
      int max_lbfgs = 20;
      ParOptInteriorPoint *opt = new ParOptInteriorPoint(sellar, max_lbfgs);
      opt->incref();

      opt->setMaxMajorIterations(100);
      opt->checkGradients(1e-6);
      
      double start = MPI_Wtime();
      opt->optimize();
      double diff = MPI_Wtime() - start;
      printf("Time taken: %f seconds \n", diff);

      sellar->decref();
      opt->decref();

      MPI_Finalize();
      return (0);
    }

The local components of the design vector can be accessed by making a call to getArray.

.. code-block:: c++

    ParOptScalar *x;
    xvec->getArray(&x);

In this case, the code can only be run in serial, so the design vector is not distributed.

All objects in ParOpt are reference counted.
Use incref() to increase the reference count after an object is allocated.
When the object is no longer needed, call decref() to decrease the reference count and possibly delete the object.
Direct calls to delete the object should not be used.

Python implementation
---------------------

The python implementation of this problem is also straightforward.
In an analogous manner, the python implemenation uses a class inherited from ParOpt.Problem, a python wrapper for the CyParOptProblem class.
This inherited class must implement a getVarsAndBounds, evalObjCon and evalObjConGradient member functions.
Note that in python, the function signature is slightly different for evalObjCon.
Please note, the vectors returned to python access the underlying memory in ParOpt directly, therefore sometimes care must be taken to avoid expressions that do not assign values to the references returned from ParOpt.
These vectors are of type ParOpt.PVec, but act in many ways like a numpy array.

.. code-block:: python

    from mpi4py import MPI
    import numpy as np
    from paropt import ParOpt

    # Create the rosenbrock function class
    class Sellar(ParOpt.Problem):
        def __init__(self):
            # Initialize the base class
            nvars = 4
            ncon = 1
            super(Sellar, self).__init__(MPI.COMM_SELF, nvars, ncon)

            return

        def getVarsAndBounds(self, x, lb, ub):
            '''Set the values of the bounds'''

            x[0] = 2.0
            x[1] = 1.0
            x[2] = 0.0
            x[3] = 0.0

            lb[0] = 0.0
            lb[1] = 0.0
            lb[2] = -1.0
            lb[3] = -1.0

            ub[0] = 10.0
            ub[1] = 10.0
            ub[2] = 3.16
            ub[3] = 24.0
            return

        def evalObjCon(self, x):
            '''Evaluate the objective and constraint'''
            fail = 0
            fobj = x[1]*x[1] + x[0] + x[2] + np.exp(-x[3])
            cons = np.array([x[0] + x[1] - 1.0])
            return fail, fobj, cons

        def evalObjConGradient(self, x, g, A):
            '''Evaluate the objective and constraint gradient'''
            fail = 0

            g[0] = 1.0
            g[1] = 2.0*x[1]
            g[2] = 1.0
            g[3] = -np.exp(-x[3])

            A[0][0] = 1.0
            A[0][1] = 1.0

            return fail

    # Allocate the optimization problem
    problem = Sellar()

    # Set up the optimization problem
    max_lbfgs = 50
    opt = ParOpt.InteriorPoint(problem, max_lbfgs, ParOpt.BFGS)

    # Optimize
    opt.optimize()