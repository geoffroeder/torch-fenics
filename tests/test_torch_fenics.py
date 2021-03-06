import pytest

import torch
import numpy as np

from fenics import *
from fenics_adjoint import *

from torch_fenics.torch_fenics import FEniCSModule, FEniCSModel


class Squares(FEniCSModel):
    def __init__(self):
        super(Squares, self).__init__()
        mesh = IntervalMesh(4, 0, 1)
        self.V = FunctionSpace(mesh, 'DG', 0)

    def forward(self, f1, f2):
        u = TrialFunction(self.V)
        v = TestFunction(self.V)

        a = u * v * dx
        L = f1**2 * f2**2 * v * dx

        u_ = Function(self.V)
        solve(a == L, u_)

        return u_

    def input_templates(self):
        return [Function(self.V), Function(self.V)]


class Poisson(FEniCSModel):
    def __init__(self):
        super(Poisson, self).__init__()
        mesh = UnitSquareMesh(10, 10)
        self.V = FunctionSpace(mesh, 'P', 1)

    def forward(self, f, g):
        u = TrialFunction(self.V)
        v = TestFunction(self.V)

        a = inner(grad(u), grad(v)) * dx
        L = f * v * dx

        # TODO: The DirichletBC block fails if not g is input directly
        bc = DirichletBC(self.V, g, 'on_boundary')

        u_ = Function(self.V)
        solve(a == L, u_, bc)

        return u_

    def input_templates(self):
        return [Constant(0),
                Constant(0)]


class DoublePoisson(FEniCSModel):
    def __init__(self):
        super(DoublePoisson, self).__init__()
        mesh = UnitIntervalMesh(10)
        self.V = FunctionSpace(mesh, 'P', 1)
        self.bc = DirichletBC(self.V, Constant(0), 'on_boundary')

    def forward(self, f1, f2):
        u = TrialFunction(self.V)
        v = TestFunction(self.V)

        a = inner(grad(u), grad(v)) * dx
        L1 = f1 * v * dx
        L2 = f2 * v * dx

        u1 = Function(self.V)
        solve(a == L1, u1, self.bc)

        u2 = Function(self.V)
        solve(a == L2, u2, self.bc)

        return u1, u2, f1, f2

    def input_templates(self):
        return [Constant(0), Constant(0)]


class Stokes(FEniCSModel):
    def __init__(self):
        super(Stokes, self).__init__()
        mesh = UnitSquareMesh(3, 3)

        VH = VectorElement('P', mesh.ufl_cell(), 2)
        QH = FiniteElement('P', mesh.ufl_cell(), 1)
        WH = VH * QH

        self.W = FunctionSpace(mesh, WH)
        self.V, self.Q = self.W.split()

        noslip_boundary = '(near(x[1], 0) || near(x[1], 1)) && on_boundary'
        noslip_bc = DirichletBC(self.V, Constant((0, 0)), noslip_boundary)

        inflow = Expression(("-sin(x[1]*pi)", "0.0"), degree=2)
        inflow_boundary = 'near(x[0], 0) && on_boundary'
        inflow_bc = DirichletBC(self.V, inflow, inflow_boundary)

        outlet_boundary = 'near(x[0], 1) && on_boundary'
        outlet_bc = DirichletBC(self.Q, Constant(0), outlet_boundary)

        self.bcs = [noslip_bc, inflow_bc, outlet_bc]

    def input_templates(self):
        return [Constant((0, 0))]

    def forward(self, f):
        u, p = TrialFunctions(self.W)
        v, q = TestFunctions(self.W)
        a = (inner(grad(u), grad(v)) - div(v) * p + q * div(u)) * dx
        L = inner(f, v) * dx

        w = Function(self.W)
        solve(a == L, w, self.bcs)

        # TODO: Temporary workaround instead of using w.split()
        u, p = split(w)
        u = project(u, self.V.collapse())
        p = project(p, self.Q.collapse())

        return u, p


def test_squares():
    f1 = torch.autograd.Variable(torch.tensor([[1, 2, 3, 4],
                                               [2, 3, 5, 6]]).double(), requires_grad=True)
    f2 = torch.autograd.Variable(torch.tensor([[2, 3, 5, 6],
                                               [1, 2, 2, 1]]).double(), requires_grad=True)
    fenics = FEniCSModule(Squares())
    assert np.all(fenics(f1, f2) == f1**2 * f2**2)
    assert torch.autograd.gradcheck(fenics, (f1, f2))


def test_poisson():
    f = torch.tensor([[1.0]], requires_grad=True).double()
    g = torch.tensor([[0.0]], requires_grad=True).double()
    fenics = FEniCSModule(Poisson())
    assert torch.autograd.gradcheck(fenics, (f, g))


def test_doublepoisson():
    f1 = torch.tensor([[1.0]], requires_grad=True).double()
    f2 = torch.tensor([[2.0]], requires_grad=True).double()
    fenics = FEniCSModule(DoublePoisson())
    assert torch.autograd.gradcheck(fenics, (f1, f2))


def test_stokes():
    f = torch.tensor([[1.0, 1.0]], requires_grad=True).double()
    fenics = FEniCSModule(Stokes())
    assert torch.autograd.gradcheck(fenics, (f,))


def test_input_type():
    f = np.array([[1.0]])
    g = np.array([[0.0]])
    fenics = FEniCSModule(Poisson())
    fenics(f, g)
    with pytest.raises(TypeError):
        f = np.array([[1.0]], dtype=np.float32)
        g = np.array([[0.0]], dtype=np.float32)
        fenics(f, g)

    f = torch.tensor([[1.0]]).double()
    g = torch.tensor([[0.0]]).double()
    fenics = FEniCSModule(Poisson())
    fenics(f, g)
    with pytest.raises(TypeError):
        f = torch.tensor([[1.0]]).float()
        g = torch.tensor([[0.0]]).float()
        fenics = FEniCSModule(Poisson())
        fenics(f, g)
