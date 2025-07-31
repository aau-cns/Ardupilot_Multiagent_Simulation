#!/bin/bash

WORKSPACE=${PWD}

# Build Ardupilot multiagent Simulation workspace 
source /workspace/ardu_ws/install/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install

# Save GZ Version to bashrc
GZ_VERSION="export GZ_VERSION=harmonic"
grep -qxF "$GZ_VERSION" ~/.bashrc || echo "$GZ_VERSION" >> ~/.bashrc

# Append sourcing to bashrc (only once)
SETUP_LINE="source $WORKSPACE/install/setup.bash"
grep -qxF "$SETUP_LINE" ~/.bashrc || echo "$SETUP_LINE" >> ~/.bashrc

# Append Gazebo resource path to bashrc (only once)
GZ_PATH_LINE="export GZ_SIM_RESOURCE_PATH=$GZ_SIM_RESOURCE_PATH:$WORKSPACE/src/multiagent_simulation/models:$WORKSPACE/src/multiagent_simulation/worlds:$WORKSPACE/src"
grep -qxF "$GZ_PATH_LINE" ~/.bashrc || echo "$GZ_PATH_LINE" >> ~/.bashrc