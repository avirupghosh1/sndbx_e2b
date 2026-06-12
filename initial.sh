#!/bin/bash

export MY_SANDBOX_API_URL=http://127.0.0.1:8000
export MY_SANDBOX_API_KEY=test-key-12345
export OPENROUTER_API_KEY=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
export OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free
export USE_OLLAMA=0
export SANDBOX_ISOLATION=firecracker
export OLLAMA_MODEL=gemma3
export SANDBOX_WARM_POOL_SIZE=0
export DEEPAGENTS_USER_PROMPT_FILE=/home/avirup/sndbx_e2b/examples/prompt
export SANDBOX_ENGINE=firecracker
export FIRECRACKER_BINARY=/usr/bin/firecracker
export FIRECRACKER_KERNEL=/home/avirup/fc-assets/vmlinux
export FIRECRACKER_ROOTFS=/home/avirup/fc-assets/rootfs.ext4
export FIRECRACKER_SSH_KEY=/home/avirup/fc-assets/fc_key
export FIRECRACKER_SSH_USER=root
export FIRECRACKER_GATEWAY=172.16.0.1
export FIRECRACKER_SUBNET_PREFIX=172.16.0
export FIRECRACKER_GUEST_OCTET_BASE=10
export FIRECRACKER_TAP_PATTERN=tapfc{slot}
export FIRECRACKER_TAP_SLOTS=8
export FIRECRACKER_SSH_KNOWN_HOSTS=/dev/null
export FIRECRACKER_ENABLE_PCI=false