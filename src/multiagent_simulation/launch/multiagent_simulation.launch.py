import os
import tempfile
from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext, LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess,
                            IncludeLaunchDescription, OpaqueFunction,
                            RegisterEventHandler)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit, OnProcessStart
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def replace_robot_name(input_file, robot_name):
    with open(input_file, 'r') as file:
        content = file.read()

    replaced_content = content.replace("<robot_name>", robot_name)

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".yaml")
    temp_file_name = temp_file.name

    with open(temp_file_name, 'w') as temp_file:
        temp_file.write(replaced_content)

    return temp_file_name


def load_robots_from_file(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)['robots']


def launch_setup(context: LaunchContext, *args, **kwargs):
    pkg_ros_gz_sim = get_package_share_directory("ros_gz_sim")
    pkg_ardupilot_sitl = get_package_share_directory("ardupilot_sitl")
    pkg_multiagent_simulation = get_package_share_directory("multiagent_simulation")
    
    robots_file = LaunchConfiguration("robots_config_file").perform(context)
    robots = load_robots_from_file(robots_file)

    # Convert camera and lidar xacro files to SDF.
    lidar_file = os.path.join(
        pkg_multiagent_simulation, "models", "lidar", "model.xacro"
    )
    camera_file = os.path.join(
        pkg_multiagent_simulation, "models", "camera", "model.xacro"
    )
    depth_camera_file = os.path.join(
        pkg_multiagent_simulation, "models", "depth_camera", "model.xacro"
    )
    rgbd_camera_file = os.path.join(
        pkg_multiagent_simulation, "models", "rgbd_camera", "model.xacro"
    )
    
    lidar_model_node = ExecuteProcess(
        cmd=["ros2", "run", "xacro", "xacro", "-o", lidar_file.replace(".xacro", ".sdf"), lidar_file],
        output="screen"
    )

    camera_model_node = ExecuteProcess(
        cmd=["ros2", "run", "xacro", "xacro", "-o", camera_file.replace(".xacro", ".sdf"), camera_file],
        output="screen"
    )
    
    depth_model_node = ExecuteProcess(
        cmd=["ros2", "run", "xacro", "xacro", "-o", depth_camera_file.replace(".xacro", ".sdf"), depth_camera_file],
        output="screen"
    )
    
    rgbd_model_node = ExecuteProcess(
        cmd=["ros2", "run", "xacro", "xacro", "-o", rgbd_camera_file.replace(".xacro", ".sdf"), rgbd_camera_file],
        output="screen"
    )

    # Ensure `SDF_PATH` is populated as `sdformat_urdf`` uses this rather
    # than `GZ_SIM_RESOURCE_PATH` to locate resources.
    if "GZ_SIM_RESOURCE_PATH" in os.environ:
        gz_sim_resource_path = os.environ["GZ_SIM_RESOURCE_PATH"]

        if "SDF_PATH" in os.environ:
            sdf_path = os.environ["SDF_PATH"]
            os.environ["SDF_PATH"] = sdf_path + ":" + gz_sim_resource_path
        else:
            os.environ["SDF_PATH"] = gz_sim_resource_path

    # Load SDF file.
    sdf_file = os.path.join(
        pkg_multiagent_simulation, "models", "iris_with_lidar_and_camera", "model.sdf"
    )
    
    launch_actions = [
        # Generate sensor models (Convert from xacro to SDF).
        lidar_model_node,
        RegisterEventHandler(
            OnProcessExit(
                target_action=lidar_model_node,
                on_exit=[camera_model_node]
            )
        ),
        RegisterEventHandler(
            OnProcessExit(
                target_action=camera_model_node,
                on_exit=[depth_model_node]
            )
        ),
        RegisterEventHandler(
            OnProcessExit(
                target_action=depth_model_node,
                on_exit=[rgbd_model_node]
            )
        ),
        # Gazebo.
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                PathJoinSubstitution([
                    pkg_ros_gz_sim,
                    "launch",
                    "gz_sim.launch.py"
                ])
            ),
            launch_arguments={
                "gz_args": [
                    "-v4 -s -r ",
                    PathJoinSubstitution([
                        pkg_multiagent_simulation,
                        "worlds",
                        LaunchConfiguration("world_file")
                    ])
                ]
            }.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                f'{Path(pkg_ros_gz_sim) / "launch" / "gz_sim.launch.py"}'
            ),
            launch_arguments={"gz_args": "-v4 -g"}.items(),
            condition=IfCondition(LaunchConfiguration("gui")),
        )
    ]

    for i, robot in enumerate(robots):
        instance = i
        sysid = i + 1
        
        port_offset = 10 * instance
        master_port = 5760 + port_offset
        sitl_port = 5501 + port_offset
        control_port = 9002 + port_offset
        sim_address = "127.0.0.1"
        
        tty0 = f"./dev/ttyROS{instance * 10}"
        tty1 = f"./dev/ttyROS{instance * 10 + 1}"
        
        name = robot['name']
        position = robot['position']
        
        spawn_robot =  Node(
            package="ros_gz_sim",
            executable="create",
            namespace=name,
            arguments=[
                "-world", "", "-param", "",
                "-name", name,
                "-topic", "robot_description",
                "-x", str(position[0]),
                "-y", str(position[1]),
                "-z", str(position[2]),
                "-R", str(position[3]),
                "-P", str(position[4]),
                "-Y", str(position[5]),
            ],
            output="screen",
        )
        launch_actions.append(spawn_robot)

        sitl_dds = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                [
                    PathJoinSubstitution(
                        [
                            FindPackageShare("ardupilot_sitl"),
                            "launch",
                            "sitl_dds_udp.launch.py",
                        ]
                    ),
                ]
            ),
            launch_arguments={
                # virtual_ports
                "tty0": tty0,
                "tty1": tty1,
                # micro_ros_agent
                "micro_ros_agent_ns": f"{name}",
                "baudrate": "115200",
                "device": tty0,
                # ardupilot_sitl
                "synthetic_clock": "True",
                "wipe": "False",
                "model": "json",
                "speedup": "1",
                "slave": "0",
                "instance": f"{instance}",
                "sysid": f"{sysid}",
                "uartC": f"uart:{tty1}",
                "defaults": os.path.join(
                    pkg_multiagent_simulation,
                    "config",
                    "gazebo-iris.parm",
                )
                + ","
                + os.path.join(
                    pkg_ardupilot_sitl,
                    "config",
                    "default_params",
                    "dds_udp.parm",
                ),
                "sim_address": "127.0.0.1",
                "master": f"tcp:{sim_address}:{master_port}",
                "sitl": f"{sim_address}:{sitl_port}",
            }.items(),
        )
        launch_actions.append(sitl_dds)

        # Publish /tf and /tf_static.
        with open(sdf_file, "r") as infp:
            robot_desc = infp.read()
        
        robot_desc = robot_desc.replace(
            "<fdm_port_in>9002</fdm_port_in>", f"<fdm_port_in>{control_port}</fdm_port_in>"
        )
        
        robot_state_publisher = Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            namespace=name,
            output="both",
            parameters=[
                {"robot_description": robot_desc},
                {"frame_prefix": ""},
            ],
            remappings=[
                ("/tf", "tf"),
                ("/tf_static", "tf_static"),
            ]
        )
        launch_actions.append(robot_state_publisher)

        # Bridge.
        tmp_bridge_file = replace_robot_name(os.path.join(pkg_multiagent_simulation, "config", "multiagent_lidar_camera_bridge.yaml"), name)
        bridge = Node(
            package="ros_gz_bridge",
            executable="parameter_bridge",
            namespace=name,
            parameters=[
                {
                    "config_file": tmp_bridge_file,
                    "qos_overrides./tf_static.publisher.durability": "transient_local",
                }
            ],
            output="screen",
        )
        launch_actions.append(bridge)
        
        # Mapping camera image bridge
        mapping_image_bridge = Node(
            package="ros_gz_image",
            executable="image_bridge",
            namespace=name,
            name="mapping_camera_image_bridge",
            arguments=[
                f'/world/map/model/{name}/link/mapping_camera_link/sensor/mapping_camera/image',
                '--ros-args',
                '--remap', f'/world/map/model/{name}/link/mapping_camera_link/sensor/mapping_camera/image:=mapping_camera/image',
            ],
            condition=IfCondition(LaunchConfiguration("use_mapping_camera")),
            output="screen",
        )
        launch_actions.append(mapping_image_bridge)
        
        # Navigation camera image bridge
        navigation_image_bridge = Node(
            package="ros_gz_image",
            executable="image_bridge",
            namespace=name,
            name="navigation_camera_image_bridge",
            arguments=[
                f'/world/map/model/{name}/link/navigation_camera_link/sensor/navigation_camera/image',
                '--ros-args',
                '--remap', f'/world/map/model/{name}/link/navigation_camera_link/sensor/navigation_camera/image:=navigation_camera/image'
            ],
            condition=IfCondition(LaunchConfiguration("use_navigation_camera")),
            output="screen",
        )
        launch_actions.append(navigation_image_bridge)

        # Zed camera image bridge
        zed_image_bridge = Node(
            package="ros_gz_image",
            executable="image_bridge",
            namespace=name,
            name="zed_camera_image_bridge",
            arguments=[
                f'/world/map/model/{name}/link/zed_camera_link/sensor/zed_camera/image',
                '--ros-args',
                '--remap', f'/world/map/model/{name}/link/zed_camera_link/sensor/zed_camera/image:=zed_camera/image',
            ],
            condition=IfCondition(LaunchConfiguration("use_zed_camera")),
            output="screen",
        )
        launch_actions.append(zed_image_bridge)

        # Relay - use instead of transform when Gazebo is only publishing odom -> base_link
        topic_tools_tf = Node(
            package="topic_tools",
            executable="relay",
            name="gazebo_tf_relay",
            namespace=name,
            arguments=[
                "gz/tf",
                "tf",
            ],
            output="screen",
            respawn=False,
            condition=IfCondition(LaunchConfiguration("use_gz_tf")),
        )
        launch_actions.append(
            RegisterEventHandler(
                OnProcessStart(
                    target_action=bridge,
                    on_start=[
                        topic_tools_tf
                    ]
                )
            )
        )
        
        # Relay - relays odom -> base_link from either Gazebo or custom odometry back to Ardupilot
        odometry_output_relay = Node(
            package="topic_tools",
            executable="relay",
            name="odometry_output_relay",
            namespace=name,
            arguments=[
                "tf",
                "ap/tf",
            ],
            output="screen",
            respawn=False,
        )
        launch_actions.append(odometry_output_relay)
        
        # RViz.
        rviz = Node(
            package="rviz2",
            executable="rviz2",
            namespace=name,
            arguments=[
                "-d",
                f'{Path(pkg_multiagent_simulation) / "rviz" / "iris_with_lidar_and_camera.rviz"}',
            ],
            condition=IfCondition(LaunchConfiguration("rviz")),
            remappings=[
                ("/tf", "tf"),
                ("/tf_static", "tf_static"),
            ],
        )
        launch_actions.append(rviz)

    return launch_actions


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "world_file",
                default_value="modelflughafen/model.sdf",
                description="World file to launch",
            ),
            DeclareLaunchArgument(
                "use_gz_tf", default_value="true", description="Use Gazebo TF."
            ),
            DeclareLaunchArgument(
                "gui", default_value="true", description="Run Gazebo simulation headless."
            ),
            DeclareLaunchArgument(
                "rviz", default_value="true", description="Open RViz."
            ),
            DeclareLaunchArgument(
                "use_mapping_camera", default_value="false", description="Whether to use the mapping camera."
            ),
            DeclareLaunchArgument(
                "use_navigation_camera", default_value="true", description="Whether to use the navigation camera."
            ),
            DeclareLaunchArgument(
                "use_zed_camera", default_value="false", description="Whether to use the zed camera."
            ),
            DeclareLaunchArgument(
                "robots_config_file",
                default_value=os.path.join(get_package_share_directory("multiagent_simulation"), "config", "robots.yaml"),
                description="YAML file describing robots (name, position)"
            ),
            OpaqueFunction(function=launch_setup),
        ]
    )