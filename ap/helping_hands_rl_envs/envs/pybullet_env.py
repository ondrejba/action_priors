import time
import copy
import numpy as np
import scipy
import numpy.random as npr

import pybullet as pb
import pybullet_data

from helping_hands_rl_envs.envs.base_env import BaseEnv
from helping_hands_rl_envs.simulators.pybullet.robots.ur5_simple import UR5_Simple
from helping_hands_rl_envs.simulators.pybullet.robots.kuka import Kuka
from helping_hands_rl_envs.simulators.pybullet.robots.ur5_robotiq import UR5_Robotiq
import helping_hands_rl_envs.simulators.pybullet.utils.object_generation as pb_obj_generation
from helping_hands_rl_envs.simulators import constants
from helping_hands_rl_envs.simulators.pybullet.objects.pybullet_object import PybulletObject

import pickle
import os

class NoValidPositionException(Exception):
  pass

class PyBulletEnv(BaseEnv):
  '''
  PyBullet Arm RL base class.
  '''
  def __init__(self, config):
    if 'robot' not in config:
      config['robot'] = 'ur5'
    if 'pos_candidate' not in config:
      config['pos_candidate'] = None
    if 'perfect_grasp' not in config:
      config['perfect_grasp'] = False
    if 'perfect_place' not in config:
      config['perfect_place'] = False
    if 'workspace_check' not in config:
      config['workspace_check'] = 'box'
    if 'in_hand_size' not in config:
      config['in_hand_size'] = 24
    if 'in_hand_mode' not in config:
      config['in_hand_mode'] = 'sub'
    if 'num_random_objects' not in config:
      config['num_random_objects'] = 0
    if 'check_random_obj_valid' not in config:
      config['check_random_obj_valid'] = False

    seed = config['seed']
    workspace = config['workspace']
    max_steps = config['max_steps']
    obs_size = config['obs_size']
    fast_mode = config['fast_mode']
    render = config['render']
    action_sequence = config['action_sequence']
    simulate_grasp = config['simulate_grasp']
    pos_candidate = config['pos_candidate']
    perfect_grasp = config['perfect_grasp']
    perfect_place = config['perfect_place']
    robot = config['robot']
    workspace_check = config['workspace_check']
    in_hand_size = config['in_hand_size']
    in_hand_mode = config['in_hand_mode']
    num_random_objects = config['num_random_objects']
    check_random_obj_valid = config['check_random_obj_valid']
    super(PyBulletEnv, self).__init__(seed, workspace, max_steps, obs_size, action_sequence, pos_candidate,
                                      in_hand_size, in_hand_mode)

    # Connect to pybullet and add data files to path
    if render:
      self.client = pb.connect(pb.GUI)
    else:
      self.client = pb.connect(pb.DIRECT)
    pb.setAdditionalSearchPath(pybullet_data.getDataPath())
    self.dynamic = not fast_mode

    # Environment specific variables
    self._timestep = 1. / 240.
    if robot == 'ur5':
      self.robot = UR5_Simple()
    elif robot == 'ur5_robotiq':
      self.robot = UR5_Robotiq()
    elif robot == 'kuka':
      self.robot = Kuka()
    else:
      raise NotImplementedError

    # TODO: Move this somewhere it makes sense
    self.block_original_size = 0.05
    self.block_scale_range = (0.6, 0.7)
    self.min_block_size = self.block_original_size * self.block_scale_range[0]
    self.max_block_size = self.block_original_size * self.block_scale_range[1]

    self.pick_pre_offset = 0.1
    self.pick_offset = 0.005
    self.place_pre_offset = 0.1
    self.place_offset = self.block_scale_range[1]*self.block_original_size

    # Setup camera parameters
    workspace_x_offset = (workspace[0][1] - workspace[0][0])/2
    workspace_y_offset = (workspace[1][1] - workspace[1][0])/2
    self.view_matrix = pb.computeViewMatrixFromYawPitchRoll([workspace[0].mean(), workspace[1].mean(), 0], 10, -90, -90, 0, 2)
    self.proj_matrix = pb.computeProjectionMatrix(-workspace_x_offset, workspace_x_offset, -workspace_y_offset, workspace_y_offset, -10.0, 100.0)
    # self.view_matrix = pb.computeViewMatrixFromYawPitchRoll([workspace[0].mean(), workspace[1].mean(), 0], 3, -90, -90, 0, 2)
    # self.proj_matrix = pb.computeProjectionMatrixFOV(5.7, 1, 2, 3.01)

    # Rest pose for arm
    rot = pb.getQuaternionFromEuler([0, np.pi, 0])
    self.rest_pose = [[0.0, 0.5, 0.5], rot]

    self.objects = list()
    self.object_types = {}

    self.simulate_grasp = simulate_grasp
    self.perfect_grasp = perfect_grasp
    self.perfect_place = perfect_place

    self.workspace_check = workspace_check

    self.table_id = None
    self.heightmap = None
    self.current_episode_steps = 1
    self.last_action = None
    self.last_obj = None
    self.state = {}
    self.pb_state = None

    self.initialize()

    self.num_random_objects = num_random_objects
    self.check_random_obj_valid = check_random_obj_valid

    self.episode_count = 0

  def initialize(self):
    ''''''
    pb.resetSimulation()
    pb.setTimeStep(self._timestep)

    pb.setGravity(0, 0, -10)
    self.table_id = pb.loadURDF('plane.urdf', [0,0,0])

    # Load the UR5 and set it to the home positions
    self.robot.initialize()

    # Reset episode vars
    self.objects = list()
    self.object_types = {}

    self.heightmap = None
    self.current_episode_steps = 1
    self.last_action = None

    # Step simulation
    pb.stepSimulation()

    return self._getObservation()

  def reset(self):
    self.episode_count += 1
    # TODO: objects sometimes don't get properly removed without hard resets
    if self.episode_count >= 1:
      self.initialize()
      self.episode_count = 0

    for o in self.objects:
      pb.removeBody(o.object_id)
    self.robot.reset()
    self.objects = list()
    self.object_types = {}
    self.heightmap = None
    self.current_episode_steps = 1
    self.last_action = None
    self.last_obj = None
    self.state = {}
    self.pb_state = None

    while True:
      try:
        self._generateShapes(constants.RANDOM, self.num_random_objects, random_orientation=True)
      except Exception as e:
        continue
      else:
        break

    pb.stepSimulation()

    return self._getObservation()

  def getStateDict(self):
    self.robot.saveState()
    state = {'current_episode_steps': copy.deepcopy(self.current_episode_steps),
             'objects': copy.deepcopy(self.objects),
             'object_types': copy.deepcopy(self.object_types),
             'heightmap': copy.deepcopy(self.heightmap),
             'robot_state': copy.deepcopy(self.robot.state),
             'random_state': np.random.get_state(),
             'last_action': self.last_action,
             'last_obj': self.last_obj
             }
    return state

  def restoreStateDict(self, state):
    self.current_episode_steps = state['current_episode_steps']
    self.objects = state['objects']
    self.object_types = state['object_types']
    self.heightmap = state['heightmap']
    self.last_action = state['last_action']
    self.last_obj = state['last_obj']
    self.robot.state = state['robot_state']
    self.robot.restoreState()
    np.random.set_state(state['random_state'])

  def saveState(self):
    self.pb_state = pb.saveState()
    self.state = self.getStateDict()

  def restoreState(self):
    pb.restoreState(self.pb_state)
    self.restoreStateDict(self.state)

  def saveEnvToFile(self, path):
    bullet_file = os.path.join(path, 'env.bullet')
    pickle_file = os.path.join(path, 'env.pickle')
    pb.saveBullet(bullet_file)
    state = self.getStateDict()
    with open(pickle_file, 'wb') as f:
      pickle.dump(state, f)

  def loadEnvFromFile(self, path):
    bullet_file = os.path.join(path, 'env.bullet')
    pickle_file = os.path.join(path, 'env.pickle')
    pb.restoreState(fileName=bullet_file)
    with open(pickle_file, 'rb') as f:
      state = pickle.load(f)
    self.restoreStateDict(state)

  def takeAction(self, action):
    motion_primative, x, y, z, rot = self._decodeAction(action)
    self.last_action = action
    self.last_obj = self.robot.holding_obj

    # Get transform for action
    pos = [x, y, z]
    # [-pi, 0] is easier for the arm(kuka) to execute
    while rot < -np.pi:
      rot += np.pi
    while rot > 0:
      rot -= np.pi
    rot_q = pb.getQuaternionFromEuler([0, np.pi, rot])

    # Take action specfied by motion primative
    if motion_primative == constants.PICK_PRIMATIVE:
      if self.perfect_grasp and not self._checkPerfectGrasp(x, y, z, rot, self.objects):
        return
      self.robot.pick(pos, rot_q, self.pick_pre_offset, dynamic=self.dynamic,
                      objects=self.objects, simulate_grasp=self.simulate_grasp)
    elif motion_primative == constants.PLACE_PRIMATIVE:
      obj = self.robot.holding_obj
      if self.robot.holding_obj is not None:
        if self.perfect_place and not self._checkPerfectPlace(x, y, z, rot, self.objects):
          return
        self.robot.place(pos, rot_q, self.place_pre_offset,
                         dynamic=self.dynamic, simulate_grasp=self.simulate_grasp)
    elif motion_primative == constants.PUSH_PRIMATIVE:
      pass
    else:
      raise ValueError('Bad motion primative supplied for action.')

  def isSimValid(self):
    for obj in self.objects:
      if not self.check_random_obj_valid and self.object_types[obj] == constants.RANDOM:
        continue
      if self._isObjectHeld(obj):
        continue
      p = obj.getPosition()
      if self.workspace_check == 'point':
        if not self._isPointInWorkspace(p):
          return False
      else:
        if not self._isObjectWithinWorkspace(obj):
          return False
      if self.pos_candidate is not None:
        if np.abs(self.pos_candidate[0] - p[0]).min() > 0.02 or np.abs(self.pos_candidate[1] - p[1]).min() > 0.02:
          return False
    return True

  def wait(self, iteration):
    if not self.simulate_grasp and self._isHolding():
      return
    [pb.stepSimulation() for _ in range(iteration)]

  def didBlockFall(self):
    motion_primative, x, y, z, rot = self._decodeAction(self.last_action)
    obj = self.last_obj

    return motion_primative == constants.PLACE_PRIMATIVE and \
           np.abs(z - obj.getPosition()[-1]) > obj.getHeight()

  def _isPointInWorkspace(self, p):
    '''
    Checks if the given point is within the workspace

    Args:
      - p: [x, y, z] point

    Returns: True in point is within workspace, False otherwise
    '''
    return self.workspace[0][0] < p[0] < self.workspace[0][1] and \
           self.workspace[1][0] < p[1] < self.workspace[1][1] and \
           self.workspace[2][0] < p[2] < self.workspace[2][1]

  def _getHeightmap(self):
    image_arr = pb.getCameraImage(width=self.heightmap_size, height=self.heightmap_size,
                                  viewMatrix=self.view_matrix, projectionMatrix=self.proj_matrix)
    depthImg = image_arr[3]
    # far = 3.01
    # near = 2
    far = 100
    near = -10
    depth = far * near / (far - (far - near) * depthImg)
    return depth.max() - depth

  def _getObservation(self, action=None):
    ''''''
    old_heightmap = self.heightmap
    self.heightmap = self._getHeightmap()

    if action is None or self._isHolding() == False:
      in_hand_img = self.getEmptyInHand()
    else:
      motion_primative, x, y, z, rot = self._decodeAction(action)
      in_hand_img = self.getInHandImage(old_heightmap, x, y, z, rot, self.heightmap)


    return self._isHolding(), in_hand_img, self.heightmap.reshape([self.heightmap_size, self.heightmap_size, 1])

  def _getValidPositions(self, padding, min_distance, existing_positions, num_shapes, sample_range=None):
    existing_positions_copy = copy.deepcopy(existing_positions)
    valid_positions = list()
    for i in range(num_shapes):
      # Generate random drop config
      x_extents = self.workspace[0][1] - self.workspace[0][0]
      y_extents = self.workspace[1][1] - self.workspace[1][0]

      is_position_valid = False
      for j in range(100):
        if is_position_valid:
          break
        if sample_range:
          sample_range[0][0] = max(sample_range[0][0], self.workspace[0][0]+padding/2)
          sample_range[0][1] = min(sample_range[0][1], self.workspace[0][1]-padding/2)
          sample_range[1][0] = max(sample_range[1][0], self.workspace[1][0]+padding/2)
          sample_range[1][1] = min(sample_range[1][1], self.workspace[1][1]-padding/2)
          position = [(sample_range[0][1] - sample_range[0][0]) * npr.random_sample() + sample_range[0][0],
                      (sample_range[1][1] - sample_range[1][0]) * npr.random_sample() + sample_range[1][0]]
        else:
          position = [(x_extents - padding) * npr.random_sample() + self.workspace[0][0] + padding / 2,
                      (y_extents - padding) * npr.random_sample() + self.workspace[1][0] + padding / 2]

        if self.pos_candidate is not None:
          position[0] = self.pos_candidate[0][np.abs(self.pos_candidate[0] - position[0]).argmin()]
          position[1] = self.pos_candidate[1][np.abs(self.pos_candidate[1] - position[1]).argmin()]
          if not (self.workspace[0][0]+padding/2 < position[0] < self.workspace[0][1]-padding/2 and
                  self.workspace[1][0]+padding/2 < position[1] < self.workspace[1][1]-padding/2):
            continue

        if existing_positions_copy:
          distances = np.array(list(map(lambda p: np.linalg.norm(np.array(p)-position), existing_positions_copy)))
          is_position_valid = np.all(distances > min_distance)
          # is_position_valid = np.all(np.sum(np.abs(np.array(positions) - np.array(position[:-1])), axis=1) > min_distance)
        else:
          is_position_valid = True
      if is_position_valid:
        existing_positions_copy.append(position)
        valid_positions.append(position)
      else:
        break
    if len(valid_positions) == num_shapes:
      return valid_positions
    else:
      raise NoValidPositionException

  def _generateShapes(self, shape_type=0, num_shapes=1, scale=None, pos=None, rot=None,
                      min_distance=None, padding=None, random_orientation=False, z_scale=1,
                      small_random_orientation=False):
    # small random orientation: blocks can still be grasped by the gripper with fixed orientation,
    # but they deviate from their default orientation a bit
    if padding is None:
      if shape_type in (constants.CUBE, constants.TRIANGLE, constants.RANDOM, constants.CYLINDER):
        padding = self.max_block_size * 1.5
      elif shape_type == constants.BRICK:
        padding = self.max_block_size * 3.4
      elif shape_type == constants.ROOF:
        padding = self.max_block_size * 3.4

    if min_distance is None:
      if shape_type in (constants.CUBE, constants.TRIANGLE, constants.RANDOM, constants.CYLINDER):
        min_distance = self.max_block_size * 2.4
      elif shape_type == constants.BRICK:
        min_distance = self.max_block_size * 3.4
      elif shape_type == constants.ROOF:
        min_distance = self.max_block_size * 3.4

    shape_handles = list()
    positions = [o.getXYPosition() for o in self.objects]

    valid_positions = self._getValidPositions(padding, min_distance, positions, num_shapes)
    if valid_positions is None:
      return None

    for position in valid_positions:
      position.append(0.05)
      if random_orientation:
        orientation = pb.getQuaternionFromEuler([0., 0., 2*np.pi*np.random.random_sample()])
      elif small_random_orientation:
        tmp_zero_one = np.random.random_sample()
        tmp_plus_minus = np.random.choice([-1.0, 1.0])
        orientation = pb.getQuaternionFromEuler([0., 0., tmp_plus_minus * (1/16) * np.pi * tmp_zero_one])
      else:
        orientation = pb.getQuaternionFromEuler([0., 0., 0])
      if not scale:
        scale = npr.uniform(self.block_scale_range[0], self.block_scale_range[1])

      if shape_type == constants.CUBE:
        handle = pb_obj_generation.generateCube(position, orientation, scale)
      elif shape_type == constants.BRICK:
        handle = pb_obj_generation.generateBrick(position, orientation, scale)
      elif shape_type == constants.TRIANGLE:
        handle = pb_obj_generation.generateTriangle(position, orientation, scale)
      elif shape_type == constants.ROOF:
        handle = pb_obj_generation.generateRoof(position, orientation, scale)
      elif shape_type == constants.CYLINDER:
        handle = pb_obj_generation.generateCylinder(position, orientation, scale)
      elif shape_type == constants.RANDOM:
        handle = pb_obj_generation.generateRandomObj(position, orientation, scale, z_scale)
      else:
        raise NotImplementedError
      shape_handles.append(handle)
    self.objects.extend(shape_handles)

    for h in shape_handles:
      self.object_types[h] = shape_type

    self.wait(50)
    return shape_handles

  def getObjects(self):
    objs = list()
    for obj in self.objects:
      if self._isObjectHeld(obj):
        continue
      objs.append(obj)
    return objs

  def getObjectPoses(self, objects=None):
    if objects is None: objects = self.objects

    obj_poses = list()
    for obj in objects:
      if self._isObjectHeld(obj):
        continue
      pos, rot = obj.getPose()
      rot = self.convertQuaternionToEuler(rot)

      obj_poses.append(pos + rot)
    return np.array(obj_poses)

  def getObjectPositions(self):
    obj_positions = list()
    for obj in self.objects:
      if self._isObjectHeld(obj):
        continue
      obj_positions.append(obj.getPosition())
    return np.array(obj_positions)

  def _getHoldingObj(self):
    return self.robot.holding_obj

  def _getHoldingObjType(self):
    return self.object_types[self._getHoldingObj()] if self.robot.holding_obj else None

  def _isHolding(self):
    return self.robot.holding_obj is not None

  def _getRestPoseMatrix(self):
    T = np.eye(4)
    T[:3, :3] = np.array(pb.getMatrixFromQuaternion(self.rest_pose[1])).reshape((3, 3))
    T[:3, 3] = self.rest_pose[0]
    return T

  def _isObjectHeld(self, obj):
    return self.robot.holding_obj == obj

  def _removeObject(self, obj):
    if obj in self.objects:
      pb.removeBody(obj.object_id)
      # self._moveObjectOutWorkspace(obj)
      self.objects.remove(obj)
      self.robot.openGripper()

  def _moveObjectOutWorkspace(self, obj):
    pos = [-0.50, 0, 0.25]
    obj.resetPose(pos, pb.getQuaternionFromEuler([0., 0., 0.]))

  def _isObjOnTop(self, obj, objects=None):
    if not objects:
      objects = self.objects
    obj_position = obj.getPosition()
    for o in objects:
      if self._isObjectHeld(o) or o is obj:
        continue
      block_position = o.getPosition()
      if np.allclose(block_position[:-1], obj_position[:-1],
                     atol=self.block_original_size * self.block_scale_range[0] * 2 / 3) and \
          block_position[-1] > obj_position[-1]:
        return False
    return True

  def _isObjOnGround(self, obj):
    contact_points = obj.getContactPoints()
    for p in contact_points:
      if p[2] == self.table_id:
        return True
    return False

  def _getNumTopBlock(self, blocks=None):
    if not blocks:
      blocks = self.objects
    cluster_pos = []
    for obj in blocks:
      if self._isObjectHeld(obj):
        continue
      block_position = obj.getPosition()
      cluster_flag = False
      for cluster in cluster_pos:
        if np.allclose(block_position[:-1], cluster, atol=self.block_original_size*self.block_scale_range[0]*2/3):
          cluster.append(block_position[:-1])
          cluster_flag = True
          break
      if not cluster_flag:
        cluster_pos.append([block_position[:-1]])
    return len(cluster_pos) + self._isHolding()

  def _checkStack(self, objects=None):
    if not objects:
      objects = self.objects
    for obj in objects:
      if self._isObjectHeld(obj):
        return False

    objects = sorted(objects, key=lambda o: o.getZPosition())
    for i, obj in enumerate(objects):
      if i == 0:
        continue
      #TODO: not 100% sure about this
      if not obj.isTouching(objects[i-1]) or obj.isTouching(PybulletObject(-1, self.table_id)):
        return False
    return True

  def _checkPerfectGrasp(self, x, y, z, rot, objects):
    end_pos = np.array([x, y, z])
    sorted_obj = sorted(objects, key=lambda o: np.linalg.norm(end_pos - o.getPosition()))
    obj_pos, obj_rot = sorted_obj[0].getPose()
    obj_type = self.object_types[sorted_obj[0]]
    obj_rot = pb.getEulerFromQuaternion(obj_rot)
    angle = np.pi - np.abs(np.abs(rot - obj_rot[2]) - np.pi)
    if obj_type is constants.CUBE:
      while angle > np.pi / 2:
        angle -= np.pi / 2
      angle = min(angle, np.pi / 2 - angle)
    elif obj_type is constants.TRIANGLE or obj_type is constants.ROOF:
      angle = abs(angle - np.pi/2)
      angle = min(angle, np.pi - angle)
    return angle < np.pi / 12

  def _checkPerfectPlace(self, x, y, z, rot, objects):
    end_pos = np.array([x, y, z])
    sorted_obj = sorted(objects, key=lambda o: np.linalg.norm(end_pos - o.getPosition()))
    obj_pos, obj_rot = sorted_obj[0].getPose()
    obj_type = self.object_types[sorted_obj[0]]
    obj_rot = pb.getEulerFromQuaternion(obj_rot)
    angle = np.pi - np.abs(np.abs(rot - obj_rot[2]) - np.pi)
    if angle > np.pi/2:
      angle -= np.pi/2
    angle = min(angle, np.pi / 2 - angle)
    return angle < np.pi / 12

  def _checkObjUpright(self, obj, threshold=np.pi/9):
    triangle_rot = obj.getRotation()
    triangle_rot = pb.getEulerFromQuaternion(triangle_rot)
    return abs(triangle_rot[0]) < threshold and abs(triangle_rot[1]) < threshold

  def _checkOnTop(self, bottom_obj, top_obj):
    bottom_position = bottom_obj.getPosition()
    top_position = top_obj.getPosition()
    if top_position[-1] - bottom_position[-1] < 0.5 * self.block_scale_range[0] * self.block_original_size:
      return False
    return top_obj.isTouching(bottom_obj)

  def _checkInBetween(self, obj0, obj1, obj2, threshold=None):
    if not threshold:
      threshold = self.max_block_size
    position0 = obj0.getXYPosition()
    position1 = obj1.getXYPosition()
    position2 = obj2.getXYPosition()
    middle_point = np.mean((np.array(position1), np.array(position2)), axis=0)
    dist = np.linalg.norm(middle_point - position0)
    return dist < threshold

  def _checkOriSimilar(self, objects, threshold=np.pi/7):
    oris = list(map(lambda o: pb.getEulerFromQuaternion(o.getRotation())[2], objects))
    return np.allclose(oris, oris, threshold)

  def _getPrimativeHeight(self, motion_primative, x, y):
    '''
    Get the z position for the given action using the current heightmap.
    Args:
      - motion_primative: Pick/place motion primative
      - x: X coordinate for action
      - y: Y coordinate for action
      - offset: How much to offset the action along approach vector
    Returns: Valid Z coordinate for the action
    '''
    x_pixel, y_pixel = self._getPixelsFromPos(x, y)
    if self._isHolding():
      if self.object_types[self.robot.holding_obj] is constants.BRICK:
        extend = int(2*self.max_block_size/self.heightmap_resolution)
      elif self.object_types[self.robot.holding_obj] is constants.ROOF:
        extend = int(1.5*self.max_block_size/self.heightmap_resolution)
      else:
        extend = int(0.5*self.max_block_size/self.heightmap_resolution)
    else:
      extend = int(0.5*self.max_block_size/self.heightmap_resolution)
    local_region = self.heightmap[int(max(x_pixel - extend, 0)):int(min(x_pixel + extend, self.heightmap_size)), \
                                  int(max(y_pixel - extend, 0)):int(min(y_pixel + extend, self.heightmap_size))]
    try:
      safe_z_pos = np.max(local_region) + self.workspace[2][0]
    except ValueError:
      safe_z_pos = self.workspace[2][0]
    if motion_primative == constants.PICK_PRIMATIVE:
      safe_z_pos -= self.pick_offset
      safe_z_pos = max(safe_z_pos, 0.02)
    else:
      safe_z_pos += self.place_offset
    return safe_z_pos

  def convertQuaternionToEuler(self, rot):
    rot = list(pb.getEulerFromQuaternion(rot))

    # TODO: This normalization should be improved
    while rot[2] < 0:
      rot[2] += np.pi
    while rot[2] > np.pi:
      rot[2] -= np.pi

    return rot

