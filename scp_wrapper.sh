#!/bin/bash

# Save the parent PID (for debugging, optional)
echo $$ > /tmp/scp_wrapper_parent.pid

# Start SCP in the background
(
  scp "$@" &
  echo $! > scp_actual.pid  # Save SCP PID to this file
  wait $!  # Wait for SCP to finish
) &
wait $!  # Wait for the background job to finish

