import torch
import numpy as np
from botorch.models import SingleTaskGP
from botorch.fit import fit_gpytorch_mll
from gpytorch.mlls import ExactMarginalLogLikelihood
from botorch.acquisition import qLogExpectedImprovement
from botorch.optim import optimize_acqf_mixed, optimize_acqf
from botorch.sampling.normal import SobolQMCNormalSampler
from Kernel import MixedSingleTaskGP
from sklearn.metrics import r2_score
from skopt.utils import normalize_dimensions
from skopt.space import Real, Categorical, Space
from transformer import transform, i_transform


def encode_conditions(condition, space):
    n_real = sum(1 for d in space.dimensions if str(type(d)).split('.')[-1][0:-2] == 'Real')
    encoded = []
    for row in condition:
        real_part = []
        cat_part = []
        for j, dim in enumerate(space.dimensions):
            para_type = str(type(dim)).split('.')[-1][0:-2]
            if para_type == 'Real':
                real_part.append((row[j] - dim.low) / (dim.high - dim.low))
            else:
                cat_part.append(dim.categories.index(row[j]))
        encoded.append(real_part + cat_part)
    return np.array(encoded, dtype=np.float64)


def data2space(space_info):
    para = []
    for j in space_info:
        if j['type'] == 'continuous':
            para.append(Real(j['range'][0], j['range'][1], name=j['name']))
    for j in space_info:
        if j['type'] == 'categorical':
            para.append(Categorical(j['range'], name=j['name']))
    space = Space(normalize_dimensions(para))
    return space



def get_next_exps(data):
    space_data = data['design_space']
    space = data2space(space_data)
    # reaction = data['reaction']
    # space = get_space(reaction)
    goal = data['goal']
    condition = data['condition']
    initialization_number = data['num_of_init']
    if condition:
        x = encode_conditions(condition, space)
        y = data['outcomes']
        q = data['q']
        train_x = torch.tensor(x, dtype=torch.float64)
        train_y = torch.tensor(y, dtype=torch.float64).unsqueeze(1)
        if len(goal) == 1:
            if goal[0]["target"] != 'max':
                train_y = -1 * train_y
        x_dim = train_x.size()[1]
        if not space.is_real:
            cat_index = []
            n_real = 0
            for j, i in enumerate(space.dimensions):
                para_type = str(type(i)).split('.')[-1][0:-2]
                if para_type == 'Categorical':
                    cat_index.append([j, len(i.bounds)])
                elif para_type == 'Real':
                    n_real += 1
            n_cat = n_real + len(cat_index)
            fixed_features_list = []
            cat_ranges = [list(range(len(dim.bounds))) for dim in space.dimensions
                          if str(type(dim)).split('.')[-1][0:-2] == 'Categorical']
            from itertools import product
            for combo in product(*cat_ranges):
                cat_dict = {}
                for idx, val in enumerate(combo):
                    cat_dict[n_real + idx] = val
                fixed_features_list.append(cat_dict)
        if space.is_categorical:
            length = 3.0
            sign = -1
            i = 0
            while 1:
                if 0 < length < 6:
                    length += i * sign * 0.5
                    sign = sign * -1
                else:
                    length = (i + 1) * 0.5
                gp = MixedSingleTaskGP(train_x, train_y, cat_dims=list(range(n_real, n_cat)), prior_l=length)
                mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
                fit_gpytorch_mll(mll)
                mean = gp(train_x).mean
                train_y_n = train_y.detach().numpy().flatten()
                mean = mean.detach().numpy()
                loss = r2_score(train_y_n, mean)
                i += 1
                if loss > 0.999 or length >= 15:
                    break
        elif space.is_real:
            gp = SingleTaskGP(train_x, train_y)
            mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
            fit_gpytorch_mll(mll)
        else:
            gp = MixedSingleTaskGP(train_x, train_y, cat_dims=list(range(n_real, n_cat)))
            mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
            fit_gpytorch_mll(mll)
        sampler = SobolQMCNormalSampler(sample_shape=torch.Size([2048]))
        bounds = torch.stack([torch.zeros(x_dim), torch.ones(x_dim)])
        qEI = qLogExpectedImprovement(gp, best_f=torch.max(train_y), sampler=sampler)

        if not space.is_real:
            candidate, acq_value = optimize_acqf_mixed(
                qEI, bounds=bounds, q=q, fixed_features_list=fixed_features_list, num_restarts=20, raw_samples=200)
        else:
            candidate, acq_value = optimize_acqf(qEI, bounds=bounds, q=q, num_restarts=20, raw_samples=200)
        candidate = candidate.numpy() if hasattr(candidate, 'numpy') else np.array(candidate)

        nparam = 0
        cate_info = []
        real_info = []
        for j, i in enumerate(space):
            nparam += 1
            if str(i)[0:4] != 'Real':
                cate_info.append({'idx': j, 'cats': i.categories})
            else:
                real_info.append({'idx': j, 'low': i.low, 'high': i.high})

        result = []
        for row in candidate:
            new_row = [None] * nparam
            for info in real_info:
                val = row[info['idx']] * (info['high'] - info['low']) + info['low']
                new_row[info['idx']] = round(val, 3)
            for ci in cate_info:
                cat_idx = int(round(row[ci['idx']]))
                cat_idx = max(0, min(cat_idx, len(ci['cats']) - 1))
                new_row[ci['idx']] = ci['cats'][cat_idx]
            result.append(new_row)
        candidate = result
    else:
        candidate =space.rvs(n_samples=initialization_number)

    def format_float(num):
        return round(float(num), 3)
    formatted_candidate = []
    for sublist in candidate:
        formatted_sublist = [format_float(item) if isinstance(item, (float, np.floating)) else item for item in sublist]
        formatted_candidate.append(formatted_sublist)

    for i in formatted_candidate:
        condition.append(i)
    return data


