#include "diagnostics.h"

namespace sia {

DiagnosticCounters &diagnostics()
{
    static DiagnosticCounters counters;
    return counters;
}

}  // namespace sia
