# Feature Specification: Reusable Warehouse Connections

**Feature Branch**: `007-connection-pooling`
**Created**: 2026-09-20
**Status**: Draft

## User Scenarios & Testing *(mandatory)*

Today the API acquires a fresh connection to each half of the warehouse for every
request and discards it when the request ends. That is a deliberate and correct
choice for one long-lived process beside its databases: nothing goes stale, no pool
can be exhausted, and restarting a database cannot wedge the service.

Deployed on a platform that runs several instances of the API at once, the same
choice inverts. Connection cost is paid per request rather than once, and the total
number of connections the API can demand is the number of instances multiplied by
their concurrency — a number that grows with traffic and is bounded by nothing the
API controls. A managed database sells a fixed connection budget; crossing it turns
requests that would have succeeded into refusals.

### User Story 1 - The workbench keeps working under load (Priority: P1)

A researcher runs an experiment while colleagues are using the deployed workbench.
Their run completes and returns the same signals it always has. They do not see a
failure caused by other people using the system at the same time.

**Why this priority**: This is the failure the feature exists to prevent. Under
concurrency the current design produces refusals on requests that are themselves
perfectly valid, and the error surfaces as an unexplained failure of the
researcher's own work.

**Independent Test**: Drive concurrent requests at a deployed instance whose
database enforces a connection budget smaller than the theoretical demand, and
confirm every request is answered.

**Acceptance Scenarios**:

1. **Given** a database that permits a limited number of simultaneous connections,
   **When** more requests arrive at once than that limit would allow under
   per-request connections, **Then** every request is answered successfully.
2. **Given** several API instances serving at once, **When** they are all busy,
   **Then** the total number of connections they hold against the catalog stays
   within a configured ceiling.
3. **Given** a request that fails for its own reasons, **When** it completes,
   **Then** the connection it used is returned for reuse rather than discarded.

---

### User Story 2 - Results do not change (Priority: P1)

A researcher re-runs a saved experiment after the change and gets byte-identical
output. Two researchers running at the same time do not see each other's data, and
no request observes a partial write from another.

**Why this priority**: Equal priority to the first, because a change to connection
lifetime is a change to transaction and session lifetime. Reused connections carry
session state — uncommitted transactions, temporary settings, prepared statements —
and leaking that between requests is a correctness failure that looks like corrupt
analysis rather than an infrastructure fault.

**Independent Test**: Run the existing experiment and signal suites against the
reused-connection path and confirm identical results; concurrently execute requests
that would conflict if they shared session state and confirm they do not.

**Acceptance Scenarios**:

1. **Given** a request that leaves a transaction open or changes a session setting,
   **When** its connection is reused by a later request, **Then** the later request
   observes a clean session.
2. **Given** two requests served concurrently, **When** both read the catalog,
   **Then** neither observes data from the other's in-flight work.
3. **Given** the same experiment configuration and dataset, **When** it is run
   before and after this change, **Then** the recorded signals are identical.

---

### User Story 3 - A database restart does not require an API restart (Priority: P2)

An operator restarts the catalog database, or a connection is dropped after sitting
idle. The next request succeeds. Nobody restarts the API.

**Why this priority**: Reuse introduces a failure mode that per-request connections
do not have — a retained connection can be dead on arrival. Without recovery the
API can hold a set of unusable connections indefinitely, which is worse than the
problem being solved because it does not heal on its own.

**Independent Test**: Serve traffic, restart the database, then continue serving
without touching the API.

**Acceptance Scenarios**:

1. **Given** the API has been serving requests, **When** the database is restarted,
   **Then** subsequent requests succeed without restarting the API.
2. **Given** a connection dropped by an idle timeout, **When** it is next selected
   for a request, **Then** the request succeeds.
3. **Given** the database is unreachable, **When** requests arrive, **Then** they
   fail with a clear error and recover automatically once it returns.

---

### User Story 4 - The zero-setup demo is untouched (Priority: P2)

Someone clones the project and starts it with no databases, no credentials and no
network. It works exactly as before.

**Why this priority**: The demo path is a standing guarantee of this project and is
protected by existing tests. This feature must not make a database driver or a
connection pool a prerequisite for running the synthetic dataset.

**Independent Test**: With warehouse drivers uninstallable and no warehouse
configured, start the app and complete a full experiment run.

**Acceptance Scenarios**:

1. **Given** no warehouse is configured, **When** the application starts, **Then**
   it serves the synthetic dataset as before.
2. **Given** the warehouse drivers are not installed, **When** the application
   starts, **Then** it starts successfully and runs an experiment end to end.

---

### Edge Cases

- What happens when every reusable connection is in use and another request
  arrives? It must wait for a bounded time and then fail clearly, never wait
  forever and never open an unbounded extra connection.
- What happens when the configured ceiling is set higher than the database allows?
  The mismatch should be detectable rather than surfacing as intermittent refusals
  under load.
- What happens to a connection whose request was abandoned by the caller
  disconnecting mid-flight? It must be reclaimed.
- What happens during the window when the database is down — do failures accumulate
  and delay recovery, or does the API keep answering promptly with an error?
- What happens to long-running requests, such as an experiment reading a wide date
  range, while short requests need connections?
- What happens on a platform that suspends an idle instance and resumes it later
  with its retained connections now dead?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The API MUST reuse connections to the catalog across requests rather
  than establishing one per request.
- **FR-002**: The API MUST reuse connections to the bar store across requests rather
  than establishing one per request.
- **FR-003**: The number of simultaneous connections one API instance holds against
  each store MUST be bounded by a configured ceiling.
- **FR-004**: The ceiling MUST be configurable per deployment without code changes,
  so it can be matched to the database's budget and the instance count.
- **FR-005**: A request MUST NOT observe session state left behind by a previous
  request that used the same connection, including open transactions and altered
  session settings.
- **FR-006**: A connection MUST be returned for reuse when its request completes,
  whether the request succeeded, failed, or was abandoned by the caller.
- **FR-007**: A connection that is no longer usable MUST be discarded and replaced
  rather than handed to a request.
- **FR-008**: The API MUST recover automatically after the database becomes
  reachable again, without an API restart.
- **FR-009**: When no connection is available within a bounded wait, the request
  MUST fail with a clear error rather than waiting indefinitely.
- **FR-010**: The synthetic dataset path MUST continue to operate with no
  databases, no credentials and no network.
- **FR-011**: Starting the application MUST NOT require any database to be
  reachable, preserving the existing startup behaviour.
- **FR-012**: The observable results of every existing operation MUST be unchanged.
- **FR-013**: No analytical computation may be introduced into the request path by
  this change.
- **FR-014**: Connection acquisition, exhaustion and replacement MUST be observable
  in the existing structured logs, so a deployment nearing its ceiling can be seen
  before it starts refusing requests.

### Key Entities

- **Connection ceiling**: The maximum number of simultaneous connections one API
  instance will hold against one store. Configured per deployment.
- **Acquisition wait**: How long a request will wait for a connection before
  failing.
- **Connection health**: Whether a retained connection is still usable; determines
  whether it is handed out, discarded, or replaced.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With a catalog permitting 20 simultaneous connections, 100 requests
  arriving at once are all answered successfully.
- **SC-002**: One API instance never holds more connections against a store than
  its configured ceiling, measured at the database.
- **SC-003**: Repeated identical requests establish no new connections after the
  first, measured as connection count at the database over the run.
- **SC-004**: After the catalog is restarted while the API is serving, the API
  answers successfully within 30 seconds without being restarted.
- **SC-005**: Every existing automated test passes unchanged, and an experiment run
  before the change produces output identical to the same run after it.
- **SC-006**: The application starts and serves the synthetic dataset with no
  databases present and no warehouse drivers installed.
- **SC-007**: When connections cannot be obtained, requests fail within the
  configured wait rather than hanging.

## Assumptions

- Deployments target a container platform that may run several API instances
  concurrently and may suspend and resume them.
- The catalog and the bar store have different connection characteristics — one a
  stateful session-based database, the other an HTTP-based columnar store — and may
  need to be handled differently while meeting the same requirements.
- The connection budget of the managed database is known to whoever configures a
  deployment; this feature makes the API's demand bounded and configurable, it does
  not discover the budget.
- Per-instance bounding is the goal. Coordinating a global ceiling across instances
  is out of scope; the deployment sets the per-instance ceiling with the expected
  instance count in mind.
- Request volume remains modest. This feature removes a structural failure mode; it
  is not a general performance-optimisation effort.
- The existing dataset-selection behaviour, where the warehouse is used only when
  configured, is unchanged.
