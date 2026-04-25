import type { Ros2Scenario } from '../types/ros2'

export const scenarios: Ros2Scenario[] = [
  {
    id: 'turtlebot-nav',
    name: 'TurtleBot 导航',
    description: '激光 SLAM + Nav2 自主导航',
    icon: '🤖',
    nodes: [
      {
        id: 'lidar',
        position: { x: 40, y: 40 },
        data: {
          label: '/lidar_driver',
          nodeType: 'publisher',
          package: 'sllidar_ros2',
          description: '发布 2D 激光扫描数据',
          qos: { reliability: 'best_effort', history: 'keep_last', depth: 5 },
        },
      },
      {
        id: 'odom',
        position: { x: 40, y: 180 },
        data: {
          label: '/odom_publisher',
          nodeType: 'publisher',
          package: 'turtlebot3_node',
          description: '发布轮式里程计',
          qos: { reliability: 'reliable', depth: 10 },
        },
      },
      {
        id: 'slam',
        position: { x: 340, y: 80 },
        data: {
          label: '/slam_toolbox',
          nodeType: 'subscriber',
          package: 'slam_toolbox',
          description: '订阅激光 + odom，构建 2D 栅格地图',
        },
      },
      {
        id: 'nav2',
        position: { x: 640, y: 160 },
        data: {
          label: '/bt_navigator',
          nodeType: 'action_server',
          package: 'nav2_bt_navigator',
          description: 'Nav2 行为树导航服务端，处理 NavigateToPose',
        },
      },
      {
        id: 'rviz',
        position: { x: 340, y: 300 },
        data: {
          label: '/rviz2',
          nodeType: 'subscriber',
          package: 'rviz2',
          description: '可视化地图 / TF / 路径',
        },
      },
      {
        id: 'goal_client',
        position: { x: 940, y: 160 },
        data: {
          label: '/goal_sender',
          nodeType: 'action_client',
          package: 'user_app',
          description: '发送目标点给 Nav2',
        },
      },
    ],
    edges: [
      {
        id: 'e1',
        source: 'lidar',
        target: 'slam',
        data: { topicName: '/scan', edgeType: 'topic', msgType: 'sensor_msgs/LaserScan', hz: 10 },
      },
      {
        id: 'e2',
        source: 'odom',
        target: 'slam',
        data: { topicName: '/odom', edgeType: 'topic', msgType: 'nav_msgs/Odometry', hz: 30 },
      },
      {
        id: 'e3',
        source: 'slam',
        target: 'nav2',
        data: { topicName: '/map', edgeType: 'topic', msgType: 'nav_msgs/OccupancyGrid', hz: 1 },
      },
      {
        id: 'e4',
        source: 'slam',
        target: 'rviz',
        data: { topicName: '/map', edgeType: 'topic', msgType: 'nav_msgs/OccupancyGrid', hz: 1 },
      },
      {
        id: 'e5',
        source: 'goal_client',
        target: 'nav2',
        data: { topicName: '/navigate_to_pose', edgeType: 'action', msgType: 'nav2_msgs/NavigateToPose' },
      },
    ],
  },
  {
    id: 'camera-pipeline',
    name: '相机处理流水线',
    description: '采集 → 图像处理 → 物体检测',
    icon: '📷',
    nodes: [
      {
        id: 'cam',
        position: { x: 40, y: 140 },
        data: {
          label: '/usb_cam',
          nodeType: 'publisher',
          package: 'usb_cam',
          description: '采集并发布原始图像',
          qos: { reliability: 'best_effort', depth: 1 },
        },
      },
      {
        id: 'rectify',
        position: { x: 340, y: 60 },
        data: {
          label: '/image_rectify',
          nodeType: 'subscriber',
          package: 'image_proc',
          description: '对原始图像进行去畸变',
        },
      },
      {
        id: 'resize',
        position: { x: 340, y: 220 },
        data: {
          label: '/image_resize',
          nodeType: 'subscriber',
          package: 'image_proc',
          description: '缩放至检测模型输入尺寸',
        },
      },
      {
        id: 'detector',
        position: { x: 640, y: 140 },
        data: {
          label: '/yolo_detector',
          nodeType: 'subscriber',
          package: 'yolo_ros',
          description: '运行 YOLO 推理，输出 2D bounding box',
        },
      },
      {
        id: 'tracker',
        position: { x: 940, y: 60 },
        data: {
          label: '/object_tracker',
          nodeType: 'service_server',
          package: 'tracker_pkg',
          description: '提供目标跟踪查询服务',
        },
      },
      {
        id: 'viewer',
        position: { x: 940, y: 240 },
        data: {
          label: '/detection_viewer',
          nodeType: 'subscriber',
          package: 'rqt_image_view',
          description: '展示标注后的图像',
        },
      },
    ],
    edges: [
      {
        id: 'c1',
        source: 'cam',
        target: 'rectify',
        data: { topicName: '/image_raw', edgeType: 'topic', msgType: 'sensor_msgs/Image', hz: 30 },
      },
      {
        id: 'c2',
        source: 'rectify',
        target: 'resize',
        data: { topicName: '/image_rect', edgeType: 'topic', msgType: 'sensor_msgs/Image', hz: 30 },
      },
      {
        id: 'c3',
        source: 'resize',
        target: 'detector',
        data: { topicName: '/image_resized', edgeType: 'topic', msgType: 'sensor_msgs/Image', hz: 30 },
      },
      {
        id: 'c4',
        source: 'detector',
        target: 'tracker',
        data: { topicName: '/track_update', edgeType: 'service', msgType: 'tracker_msgs/UpdateTracks' },
      },
      {
        id: 'c5',
        source: 'detector',
        target: 'viewer',
        data: { topicName: '/detections', edgeType: 'topic', msgType: 'vision_msgs/Detection2DArray', hz: 30 },
      },
    ],
  },
  {
    id: 'manipulator',
    name: '机械臂控制',
    description: 'MoveIt2 规划 + 轨迹执行',
    icon: '🦾',
    nodes: [
      {
        id: 'joint_state',
        position: { x: 40, y: 60 },
        data: {
          label: '/joint_state_publisher',
          nodeType: 'publisher',
          package: 'joint_state_publisher',
          description: '发布关节当前状态',
          qos: { reliability: 'reliable', depth: 10 },
        },
      },
      {
        id: 'moveit',
        position: { x: 340, y: 140 },
        data: {
          label: '/move_group',
          nodeType: 'action_server',
          package: 'moveit_ros_move_group',
          description: 'MoveIt2 运动规划服务端',
        },
      },
      {
        id: 'controller',
        position: { x: 640, y: 140 },
        data: {
          label: '/joint_trajectory_controller',
          nodeType: 'action_client',
          package: 'ros2_controllers',
          description: '执行轨迹到硬件',
        },
      },
      {
        id: 'hardware',
        position: { x: 940, y: 60 },
        data: {
          label: '/hardware_interface',
          nodeType: 'subscriber',
          package: 'ros2_control',
          description: '与机械臂底层通讯',
        },
      },
      {
        id: 'ui',
        position: { x: 40, y: 240 },
        data: {
          label: '/motion_planning_ui',
          nodeType: 'action_client',
          package: 'rviz2',
          description: '用户在 RViz 中下发目标位姿',
        },
      },
      {
        id: 'gripper',
        position: { x: 940, y: 240 },
        data: {
          label: '/gripper_server',
          nodeType: 'service_server',
          package: 'gripper_pkg',
          description: '夹爪开合服务',
        },
      },
    ],
    edges: [
      {
        id: 'm1',
        source: 'joint_state',
        target: 'moveit',
        data: { topicName: '/joint_states', edgeType: 'topic', msgType: 'sensor_msgs/JointState', hz: 100 },
      },
      {
        id: 'm2',
        source: 'ui',
        target: 'moveit',
        data: { topicName: '/move_action', edgeType: 'action', msgType: 'moveit_msgs/MoveGroup' },
      },
      {
        id: 'm3',
        source: 'moveit',
        target: 'controller',
        data: { topicName: '/follow_joint_trajectory', edgeType: 'action', msgType: 'control_msgs/FollowJointTrajectory' },
      },
      {
        id: 'm4',
        source: 'controller',
        target: 'hardware',
        data: { topicName: '/joint_commands', edgeType: 'topic', msgType: 'trajectory_msgs/JointTrajectory', hz: 100 },
      },
      {
        id: 'm5',
        source: 'ui',
        target: 'gripper',
        data: { topicName: '/gripper_command', edgeType: 'service', msgType: 'gripper_msgs/SetGripper' },
      },
    ],
  },
]
