#include "realtime.hpp"

#include <sched.h>
#include <string>
#include <sys/mman.h>

namespace ksound::native {

std::string try_enable_realtime() {
    std::string result;

    if (mlockall(MCL_CURRENT | MCL_FUTURE) == 0) {
        result += "mlockall=ok ";
    } else {
        result += "mlockall=fail ";
    }

    // Do not put the whole native engine in SCHED_FIFO.
    // It spawns parec/pacat children; if they inherit realtime scheduling,
    // playback can lag badly or destabilize.
    result += "sched_fifo=disabled";

    return result;
}

} // namespace ksound::native
