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

    sched_param param{};
    param.sched_priority = 20;
    if (sched_setscheduler(0, SCHED_FIFO, &param) == 0) {
        result += "sched_fifo=ok";
    } else {
        result += "sched_fifo=fail";
    }

    return result;
}

} // namespace ksound::native
