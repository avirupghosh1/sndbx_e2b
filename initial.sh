#!/bin/bash

export MY_SANDBOX_API_URL=http://127.0.0.1:8000
export MY_SANDBOX_API_KEY=test-key-12345

export OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free
export USE_OLLAMA=1
export SANDBOX_ISOLATION=docker
export OLLAMA_MODEL=gemma3
export SANDBOX_WARM_POOL_SIZE=6