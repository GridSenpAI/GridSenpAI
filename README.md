



<img width="1024" height="1024" alt="GridSenpAI" src="https://github.com/user-attachments/assets/6e7b4374-1962-4c8e-a29b-3d00a711650e" />

# GridSenpAI
![Project Status](https://img.shields.io/badge/status-research-blue)
![Architecture](https://img.shields.io/badge/platform-watsonx-purple)
![Domain](https://img.shields.io/badge/domain-power%20systems-green)
AI-powered translation between data center electrical design and grid interconnection modeling

## TLDR

GridSenpAI translates data center electrical design information into
simulation-ready parameters for transmission planning tools such as
PSS/E, PSLF, and PowerWorld.

The system bridges the information gap between large load customers
and transmission planners by converting facility design data into
grid modeling inputs.

AI-powered translation between data center electrical design and grid interconnection modeling

GridSenpAI is an artificial intelligence platform designed to bridge the information gap between large load customers (LLCs) such as hyperscale data centers and transmission planners (TPs) responsible for grid reliability studies.

Modern data centers are highly complex electrical systems composed of UPS systems, generators, power electronics, and control systems. Transmission planners must evaluate the grid impacts of these facilities, but the information provided during interconnection applications is often incomplete or difficult to translate into power system simulation parameters.

GridSenpAI solves this problem by automatically translating facility electrical design information into model-ready parameters that can be used directly in transmission planning tools.

## Problem

Large load interconnection requests are rapidly increasing due to growth in:

• Hyperscale data centers
• AI compute clusters
• Electrified industrial loads

Transmission planners must determine how these loads will behave during:

• grid disturbances
• voltage events
• frequency events
• switching operations

However, planners often lack detailed information about how the facility’s internal electrical systems will respond to these events.

As a result:

• planners make conservative assumptions
• modeling uncertainty increases
• study timelines increase
• interconnection queues grow

GridSenpAI addresses this modeling translation gap.

## Solution

GridSenpAI uses AI-assisted engineering translation to convert facility design information into structured parameters suitable for power system simulation tools.

The system ingests information such as:

• single line electrical diagrams
• generator specifications
• UPS topology and control behavior
• facility load architecture
• electrical protection schemes

Using document intelligence and retrieval augmented generation (RAG), GridSenpAI converts this information into modeling inputs used by planners.

Outputs include parameters compatible with tools such as:

• PSS/E
• PSLF
• PowerWorld

## System Architecture

GridSenpAI uses a document intelligence and reasoning pipeline built on the IBM watsonx ecosystem.

Core components include:

**Document Ingestion**
IBM Watson Discovery

**Knowledge Retrieval (RAG)**
Watson Discovery vector retrieval

**Reasoning Engine**
watsonx.ai foundation models

**Translation Engine**
GridSenpAI parameter translation layer

**Data Storage**
IBM Cloud Object Storage
Db2 / structured parameter store

**API Layer**
IBM API Connect

**Deployment**
Red Hat OpenShift

## High Level Workflow

```
Data Center Electrical Documentation
        ↓
Document Ingestion (IBM Watson Discovery)
        ↓
Knowledge Retrieval (RAG via Watson Discovery)
        ↓
AI Reasoning (watsonx.ai foundation model)
        ↓
Parameter Translation Engine (GridSenpAI logic layer)
        ↓
Structured Output (Grid modeling parameters)
        ↓
Transmission Planning Tools
PSS/E | PSLF | PowerWorld
```

## Repository Structure
GridSenpAI
│
├── docs
│ ├── SRS
│ ├── System_Architecture
│ ├── Data_Schemas
│ ├── Algorithm_Specifications
│ ├── Test_Plan
│
├── schemas
│ ├── facility_inputs
│ ├── modeling_outputs
│
├── translation_engine
├── rag_pipeline
├── examples
└── README.md
## Core Engineering Artifacts

This repository contains the foundational system design documentation.

Key artifacts include:

• Software Requirements Specification (SRS)
• System Architecture Document
• Data Schema Documentation
• Translation Engine Algorithm Specification
• Parameter Mapping Table
• System Test Plan

These documents define the system design and engineering approach used to implement GridSenpAI.

## Parameter Translation Concept

GridSenpAI converts facility electrical design parameters into grid modeling parameters.

Example mapping:

| Facility Input | Translation Logic | Transmission Planner Parameter |
|---|---|---|
| UPS topology | infer load control behavior | ZIP load coefficients |
| Generator model | determine dynamic response | dynamic generator model |
| Load distribution | aggregate behavior | composite load model |
| Power electronics | identify fast response behavior | inverter-based resource model |

This translation layer enables planners to model large facilities more accurately.

## Project Goals

GridSenpAI aims to:

• reduce uncertainty in large load modeling
• accelerate interconnection studies
• improve grid reliability planning
• enable better communication between data center engineers and transmission planners

## Project Status
## Research Foundation

The GridSenpAI architecture is informed by:

• stakeholder interviews with transmission planners and large load developers  
• analysis of ISO interconnection procedures  
• review of industry reports on large load modeling  
• engineering research on data center electrical systems

Supporting documentation is available in the `docs` directory.
Current stage:

Research and architecture development

Active work includes:

• stakeholder interviews
• engineering parameter research
• AI translation pipeline design
• prototype system development

## Contributors

GridSenpAI is being developed as part of research into improving large load interconnection analysis.

Project contributors include engineers and researchers working in:

• power systems engineering
• data center electrical design
• artificial intelligence
• grid interconnection processes

## License

License information will be provided in this repository.

## Contact

For research collaboration or discussion regarding grid interconnection modeling challenges:

GridSenpAI Project Team
