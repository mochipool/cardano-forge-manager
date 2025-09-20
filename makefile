
# -------------------------
# Makefile for forge-manager
# -------------------------

# Default values (can be overridden)
PLATFORM ?= linux/amd64
TAG ?= ttl.sh/$(shell uuidgen):1h

# Image tool (podman or docker)
IMAGE_TOOL ?= podman

# Enable sudo for Podman/QEMU if required
USE_SUDO ?= false
ifeq ($(USE_SUDO),true)
  CMD_PREFIX = sudo
else
  CMD_PREFIX =
endif

# -------------------------
# Targets
# -------------------------

.PHONY: build
build:
	$(CMD_PREFIX) $(IMAGE_TOOL) build \
		--platform $(PLATFORM) \
		-t $(TAG) .
	@echo "Image built with tag: $(TAG)"

.PHONY: push
push: build
	$(CMD_PREFIX) $(IMAGE_TOOL) push $(TAG)
	@echo "Image pushed with tag: $(TAG)"

.PHONY: clean
clean:
	$(CMD_PREFIX) $(IMAGE_TOOL) image rm -f $(TAG) || true
