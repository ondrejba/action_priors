import subprocess
import itertools


models_path = "data/fruits_DQN_models"
dataset_path = "data/fruits_DQN_dsets"

cs = []

for i in range(1, 5):

    c = list(itertools.combinations(list(range(5)), i))
    cs += c

d_paths = []
m_paths = []

save_path = "{:s}/dset_eps_0_5_all_20k.h5".format(dataset_path)
c_string = ",".join(["".join([str(s) for s in c]) for c in cs])
print(c_string)

for c in cs:

    c = list(c)
    d_paths.append("{:s}/dset_eps_0_5_{:s}.h5".format(dataset_path, str(c)))
    m_paths.append("{:s}/model_{:s}.pt".format(models_path, str(c)))

subprocess.call([
    "python", "-m", "ap.scr.online.fruits.join_dsets", "with", "datasets_list={:s}".format(str(d_paths)),
    "models_list={:s}".format(str(m_paths)), "dset_save_path={:s}".format(save_path), "exp_per_dataset=20000",
    "c_string={:s}".format(c_string)
])
