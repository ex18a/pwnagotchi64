PWN_HOSTNAME := pwnagotchi
PWN_VERSION  := $(shell python3 -c "exec(open('pwnagotchi/_version.py').read()); print(__version__)")
PWN_RELEASE  := pwnagotchi64-$(PWN_VERSION)
SDIST        := dist/pwnagotchi64-$(PWN_VERSION).tar.gz
USER_ID      := $(shell id -u)
GROUP_ID     := $(shell id -g)

.PHONY: all clean clean-base image rebuild-base

all: clean image

image:
	@echo "--- Creating Python source distribution ---"
	mkdir -p dist
	python3 setup.py sdist

	@echo "--- Syncing filesystem and setting permissions ---"
	sync
	chmod +x builder/pwnagotchi.sh

	@echo "--- Starting Docker Build for $(PWN_RELEASE) ---"
	sudo docker run --privileged --rm \
		--dns=8.8.8.8 \
		-e FORCE_BASE=$(FORCE_BASE) \
		-v /dev:/dev \
		-v /lib/modules:/lib/modules \
		-v $(shell pwd):/build \
		-w /build \
		debian:bookworm /bin/bash -c "echo 'Acquire::ForceIPv4 \"true\";' > /etc/apt/apt.conf.d/99force-ipv4 && ./builder/pwnagotchi.sh $(PWN_VERSION) $(PWN_HOSTNAME)"

	@echo "--- SUCCESS ---"
	@echo "Build complete. Image found in dist/$(PWN_RELEASE).img"

# Forces a full rebuild of the cached stripped base image (dist/base_pwnagotchi.img)
# even if one already exists -- use this after changing apt-requirements.txt or
# anything in pwnagotchi.sh's base-stage (PHASE 4A). Every other `make image`
# reuses the existing cache and skips straight to installing pwnagotchi itself.
rebuild-base:
	$(MAKE) image FORCE_BASE=1

clean:
	@echo "Cleaning up previous build artifacts..."
	-python3 setup.py clean --all
	-rm -rf pwnagotchi.egg-info
	-sudo rm -rf builder/output-pwnagotchi builder/packer_cache
	@# Preserves both the raw Kali download and our own cached stripped base --
	@# these are what make repeat builds fast, see rebuild-base/clean-base
	-find dist -type f ! -name 'base_kali.img' ! -name 'base_pwnagotchi.img' -delete 2>/dev/null || true

# Wipes the cached base images entirely (both the raw Kali download and our
# stripped-base snapshot) -- forces the next `make image` to redo the full
# ~1hr provisioning from scratch. Use this if Kali itself needs updating, not
# just for a normal apt-requirements.txt change (see rebuild-base for that).
clean-base:
	@echo "Removing cached base images..."
	-rm -f dist/base_kali.img dist/base_pwnagotchi.img
