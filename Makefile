PWN_HOSTNAME := pwnagotchi
PWN_VERSION  := $(shell python3 -c "exec(open('pwnagotchi/_version.py').read()); print(__version__)")
PWN_RELEASE  := pwnagotchi-$(PWN_VERSION)-64bit
SDIST        := dist/pwnagotchi-$(PWN_VERSION).tar.gz
USER_ID      := $(shell id -u)
GROUP_ID     := $(shell id -g)

.PHONY: all clean image

all: clean image

image:
	@echo "--- Creating Python source distribution ---"
	mkdir -p dist
	python3 setup.py sdist

	@echo "--- Syncing filesystem and setting permissions ---"
	sync
	chmod +x builder/pwnagotchi.sh

	@echo "--- Starting Docker Build for $(PWN_RELEASE) ---"
	sudo docker run --privileged --rm -it \
		--dns=8.8.8.8 \
		-v /dev:/dev \
		-v /lib/modules:/lib/modules \
		-v $(shell pwd):/build \
		-w /build \
		debian:bookworm /bin/bash -c "echo 'Acquire::ForceIPv4 \"true\";' > /etc/apt/apt.conf.d/99force-ipv4 && ./builder/pwnagotchi.sh $(PWN_VERSION) $(PWN_HOSTNAME)"

	@echo "--- SUCCESS ---"
	@echo "Build complete. Image found in dist/$(PWN_RELEASE).img"

clean:
	@echo "Cleaning up previous build artifacts..."
	-python3 setup.py clean --all
	-rm -rf pwnagotchi.egg-info
	-sudo rm -rf builder/output-pwnagotchi builder/packer_cache
	@# FIXED: Preserves base image
	-find dist -type f ! -name 'base_kali.img' -delete 2>/dev/null || true
