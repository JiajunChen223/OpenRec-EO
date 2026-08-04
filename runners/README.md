# Runner interface (draft)

The final release should expose small path-safe entry points that pass explicit
input and output arguments to the byte-preserved scripts. Runners must not
embed workstation paths, download restricted data automatically, or modify
the frozen algorithms. Add an executable runner only after a clean-environment
test and record its hash in the release manifest.
