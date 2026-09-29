# Call overhead

Each benchmark calls an out-of-line function that returns `x + 1`. The added time is the guarded call minus a plain call in the same executable.

| Guard | Plain call | Guarded call | Added per call |
| --- | ---: | ---: | ---: |
| Manual scope | 0.987 ns | 1.38 ns | 0.39 ns |
| Manual explicit check | 0.987 ns | 1.46 ns | 0.47 ns |
| Manual scope + checked return | 0.991 ns | 1.96 ns | 0.97 ns |
| Automatic mode | 0.991 ns | 2.28 ns | 1.29 ns |

Measured with an AMD Ryzen 9 7950X3D and GCC 16.2.1, pinned to CPU 0.
