#include "system_state.h"

namespace sia {

RuntimeState &runtime_state()
{
    static RuntimeState state;
    return state;
}

}  // namespace sia
