<!--
   Copyright 2026 UCP Authors

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
-->

# Governance

## Core Principles

- Members are chosen and promoted to various committees based on their actual
  contributions.
- Members work towards the overall health and adoption of a more open
  ecosystem and agnostic to interests of the companies they represent.

## Contributors

- Open - Anyone can contribute but needs to sign a contributor license.
  See [`CONTRIBUTING.md`](CONTRIBUTING.md) for details.
- All code changes need to be approved by at least 1 maintainer elected by the
  respective Domain Tech Council (DTC), and all members of that DTC are cc’ed.

## Maintainers

- Responsible for reviewing and approving code changes to ensure they align
  with the project's technical standards and governance principles.
- Build tools and documentation to facilitate adoption of the protocol.
- Domain Tech Council (DTC) can add, remove & nominate maintainers for their
  domain as needed.
- All code changes require approval from at least one Maintainer.

### Domain Working Groups (DWG)

- Because the DTC cannot be experts in every field, Domain Working Groups
  (DWG) may be formed as a natural part of expanding the protocol.
- DWG are subject to DTC oversight - all DWG artifacts must be reviewed and
  approved by the DTC.
- Acts as the consensus venue for industry participants (e.g., multiple
  airlines) to agree on shared interoperability standards within the
  protocol, maintain the specific documentation and implementation guides for
  their domain's capabilities.
- A group of 3+ organizations can submit a charter to the Governing Council
  to form a DWG (e.g., "Travel WG"). Once chartered, the DWG has autonomy to
  define capabilities for their domain and submit for DTC approvals.

## Domain Tech Councils (Domain TC)

- Members are responsible for building and maintaining core specification for the
  respective domain.
- Members are elected by the Governing Council (GC).
- Decisions are made with a majority vote.
- Any Domain TC member may request a review from the Governing Council at any time
  for any additional inputs.
- Members are elected by the GC every 6 months, based on their technical
  contributions towards the protocol. Members can be re-elected any number of
  times. See [TC_ELECTIONS.md](TC_ELECTIONS.md) for more details.

### Shopping Tech Council (Shopping TC)

- Responsible for building and maintaining core specification for the
  Shopping domain.
- Includes 16 members, 4 permanent members from each founding organization (Google &
  Shopify), each with 1 vote (total 8 votes).
- Includes 8 members from any organization, each with 1 vote (total 8 votes).

### Food Tech Council (Food TC)

- Responsible for building and maintaining core specification for the
  Food Ordering domain.
- Includes 16 members, with 10 permanent members from founding organizations,
  6 from Google, 1 from DoorDash, Toast, Square, Uber Eats each with 1 vote
  (total 10 votes).
- Includes 6 members from any organization, each with 1 vote (total 6 votes).

## Governing Council (GC)

- Responsible for governance, overall health and adoption of the protocol.
- GC serves as the ultimate owner of all UCP assets. Google
  acts as the custodian of the UCP.dev domain, holding and managing it to
  foster adoption of UCP.
- Includes a total of 5 members.
- Includes 1 permanent member from each founding organization (Google &
  Shopify) each having 1 vote (total 2 votes).
- Includes 3 elected members from any organization, each with 1 vote (total 3
  votes), elected by the permanent founding members of the GC based on their
  contributions towards the protocol's health and adoption. Elected members are
  re-elected annually and can be re-elected any number of times.
- Open elected seats may be filled at any time via GC election and approval.
  Google holds proxy vote for all open seats until Dec 2028 to facilitate rapid
  early stage growth & adoption of the protocol.
- Can add/remove DTC members via simple majority vote.
- Can elect new members to GC based on their ability to drive protocol
  adoption, represent key industry domains, and demonstrate commitment to open
  protocols.
- May choose to review and veto a DTC decision or recommendation.
- Decisions are made with a majority vote.
- May participate in any DTC.

## Process for nominating new Domain Tech Councils (DTC)

- Submit a DTC charter nomination (using the
  [DTC charter template](DOMAIN_TECH_COUNCIL_CHARTER.md)) as a new issue
  in the [UCP Issues
  tracker](https://github.com/Universal-Commerce-Protocol/ucp/issues).
- GC reviews DTC charter and approves/rejects DTC nomination.
- GC opens up nomination for inducting DTC members, using the process
  specified in [TC_ELECTIONS.md](TC_ELECTIONS.md).
- GC elects and announces the new DTC members, finalizes the DTC
  composition and updates the governance documentation.

## Communication

To ensure the protocol remains open and agnostic, all governance activities must
be visible, accessible, and searchable. All communication that is intended to be
public (concerning, e.g., adding a capability before creating an extension,
debating one approach versus another, or announcements relating to upcoming
launches, etc.) shall take place on a shared Google group with a mailing list.
This includes discussion on enhancement proposals, announcements about official
specification changes and final governance votes.

- **DTC & DWG Meetings:** Agendas should be posted 24 hours in advance. Minutes
  and meeting notes should be published to the repository within 1 week of the
  meeting conclusion. DTC reserves the right to redact or edit meeting notes as
  needed.
- **Governing Council Meetings:** Summaries of strategic decisions and budget
  allocations will be published quarterly (specific sensitive partnership
  discussions may remain private).
