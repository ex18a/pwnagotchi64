# Pwnagotchi: 64-Bit PyTorch Edition

[![License](https://img.shields.io/badge/license-GPL3-brightgreen.svg?style=flat-square)](LICENSE.md)

This is a specialized, high-performance fork of the Pwnagotchi project. This build is designed for 64-bit architecture, utilizing **PyTorch** for AI inference and training, providing a significant boost in intelligence and processing stability over the original A2C implementation.

> **Hardware Support:** Optimized for the **Raspberry Pi Zero 2 W** and **Raspberry Pi 3B+**. 
> *Note: While other boards may work, this build specifically targets 64-bit ARM architectures.*

---

## What makes this build different?

This build removes the limitations of the original 32-bit Pwnagotchi environment. By moving to a 64-bit Kali base and integrating PyTorch, the AI is no longer bottlenecked by legacy dependencies.

### Key Custom Features
*   **PyTorch AI Engine:** Replaces the aging A2C logic with a modern PyTorch-based inference engine, allowing for faster epoch processing and more complex learning patterns.
*   **64-Bit Optimized:** Native support for 64-bit Kali Linux, fully utilizing the CPU architecture of the Pi Zero 2 W.

---
