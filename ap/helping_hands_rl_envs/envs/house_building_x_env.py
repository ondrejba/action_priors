from copy import deepcopy
from helping_hands_rl_envs.envs.pybullet_env import PyBulletEnv
from helping_hands_rl_envs.simulators import constants
from .utils.check_goal import CheckGoal
from .utils.check_goal_custom_labels import CheckGoalCustomLabels

def createHouseBuildingXEnv(simulator_base_env, config):
  class HouseBuildingXEnv(simulator_base_env):
    ''''''
    def __init__(self, config):
      if simulator_base_env is PyBulletEnv:
        super().__init__(config)
        self.block_scale_range = (0.6, 0.6)
        self.min_block_size = self.block_original_size * self.block_scale_range[0]
        self.max_block_size = self.block_original_size * self.block_scale_range[1]
      else:
        raise ValueError('Bad simulator base env specified.')
      self.simulator_base_env = simulator_base_env
      self.random_orientation = config['random_orientation'] if 'random_orientation' in config else False
      self.small_random_orientation = config['small_random_orientation'] if 'small_random_orientation' in config else False
      self.num_obj = config['num_objects'] if 'num_objects' in config else 1
      self.reward_type = config['reward_type'] if 'reward_type' in config else 'sparse'
      self.get_custom_labels = config['get_custom_labels'] if 'get_custom_labels' in config else False
      self.custom_label_goals = config['custom_label_goals'] if 'custom_label_goals' in config else None
      self.check_roof_upright = config['check_roof_upright'] if 'check_roof_upright' in config else True
      self.previous_candidates = None

      self.gen_blocks = config["gen_blocks"]
      self.gen_bricks = config["gen_bricks"]
      self.gen_triangles = config["gen_triangles"]
      self.gen_roofs = config["gen_roofs"]

      goal = config["goal_string"]
      self.check_goal = CheckGoal(goal, self)

      if self.get_custom_labels:
        assert self.custom_label_goals is not None
        # create a list of labelers for each task
        # labels give information about intermediate steps in addition to goal states
        self.check_goal_labels = [CheckGoalCustomLabels(g, self) for g in self.custom_label_goals]

    def step(self, action):
      if self.get_custom_labels:
        if self.previous_candidates is None:
          # we want to compare the env state before and after place action to label it
          self.previous_candidates = [obj.get_place_candidate_dict() for obj in self.check_goal_labels]

      self.takeAction(action)
      self.wait(100)
      obs = self._getObservation(action)
      done = self._checkTermination()
      reward = 1.0 if done else 0.0

      if not done:
        done = self.current_episode_steps >= self.max_steps or not self.isSimValid()
      self.current_episode_steps += 1

      if self.get_custom_labels:
        if action[3] == 0.0:
          # get labels for pick action
          labels = [obj.get_label_pick() for obj in self.check_goal_labels]
          self.previous_candidates = [obj.get_place_candidate_dict() for obj in self.check_goal_labels]
        else:
          # get labels for place action
          labels = []
          candidates = []

          for idx, obj in enumerate(self.check_goal_labels):
            tmp_labels, tmp_candidates = obj.get_label_place(self.previous_candidates[idx])
            labels.append(tmp_labels)
            candidates.append(tmp_candidates)

          self.previous_candidates = candidates

        return obs, reward, done, {"labels": labels}
      else:
        return obs, reward, done

    def reset(self):
      ''''''
      while True:
        super(HouseBuildingXEnv, self).reset()
        try:
          # order matters!
          self._generateShapes(
            constants.ROOF, self.gen_roofs, random_orientation=self.random_orientation,
            small_random_orientation=self.small_random_orientation
          )
          self._generateShapes(
            constants.BRICK, self.gen_bricks, random_orientation=self.random_orientation,
            small_random_orientation=self.small_random_orientation
          )
          self._generateShapes(
            constants.CUBE, self.gen_blocks, random_orientation=self.random_orientation,
            small_random_orientation=self.small_random_orientation
          )
          self._generateShapes(
            constants.TRIANGLE, self.gen_triangles, random_orientation=self.random_orientation,
            small_random_orientation=self.small_random_orientation
          )
        except Exception as e:
          continue
        else:
          break
      return self._getObservation()

    def _checkTermination(self):
      return self.check_goal.check()

    def getObjectPosition(self):
      return list(map(self._getObjectPosition, self.objects))

    def isSimValid(self):
      roofs = list(filter(lambda x: self.object_types[x] == constants.ROOF, self.objects))
      if len(roofs) > 0 and self.check_roof_upright:
        return self._checkObjUpright(roofs[0]) and super().isSimValid()
      else:
        return super().isSimValid()

  def _thunk():
    return HouseBuildingXEnv(config)

  return _thunk