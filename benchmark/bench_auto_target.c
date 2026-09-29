/* This translation unit is compiled through the automatic RETGUARD entry
   and return pipeline. */
__attribute__((noinline)) int
bench_auto(int x)
{
    return x + 1;
}
