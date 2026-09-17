# Overview

## Background

CEDARS \(Clinical Event Detection and Recording System\) is a computational paradigm for collection and aggregation of time-to-event data in retrospective clinical studies. Developed out of a practical need for a more efficient way to conduct medical research, it aims to systematize and accelerate the review of electronic health record \(EHR\) corpora to detect and characterize clinical events. Using CEDARS, human abstractors can work more efficently through the use of dedicated graphical user interface (GUI). the system also incorporates a customized data storage scheme and a natural language processing \(NLP\) pipeline. In its current iteration, CEDARS is available as an open-source Python package under [GPL-3 license](https://www.gnu.org/licenses/gpl-3.0.en.html). The latest package and previous versions can be cloned from [GitHub](https://github.com/CEDARS-NLP/CEDARS). Full documentation is available [here](https://cedars.io). CEDARS can be used with or without its companion NLP package [PINES](https://pines.ai). Please see the [Terms of Use](TERMS_OF_USE.md) before using CEDARS. **CEDARS is provided as-is with no guarantee whatsoever and users agree to be held responsible for compliance with their local government/institutional regulations.**

## General Requirements

- Python 3.9 or later
- Docker

## Basic Concepts

![CEDARS Workflow](pics/GitHub%20Schema%202%20C.png)

Sentences with keywords or concepts of interest are presented to the end user one at a time and in chronological order. The user assesses each sentence, determining whether or not a clinical event is being reported. The whole note or report drawn from the EHR is available for review in the GUI. If no event is declared in the sentence, CEDARS presents the next sentence for the same patient \(\#1\). If an event date is entered, CEDARS moves to the next unreviewed sentence before the event date. If there are no sentences left to review before the event, the GUI moves to the next patient \(\#2\) and the process is repeated with the following record \(\#3 and \#4\), until all selected sentences have been reviewed.

In order for CEDARS to be sufficiently sensitive and not miss and unacceptable number of clinical events, the keyword/concept search query must be well thought and exhaustive. The performance of CEDARS will vary by medical area, since the extent of medical lexicon will vary substantially between event types.

## Features

* `Automatic Detection of Key Events`
* `Easy interface to upload and query medical data.`
* `Project Statistics`
* `Secure Login`


## Operational Schema

![CEDARS Operational Schema](pics/GitHub%20Docker%20Schema%20C.png)

CEDARS is modular and all information for any given annotation project is stored in one MongoDB database. User credentials, original clinical notes, NLP annotations and patient-specific information are stored in dedicated collections. Once clinical notes have been uploaded, they are passed through the NLP pipeline. Currently only UDPipe is supported and integrated with CEDARS. If desired, the annotation pipeline can include negation and medical concept tagging by NegEx and UMLS respectively.

Multiple users can load the web GUI and annotate records at the same time. Once accessed, a given patient record is locked for the user.

## AWS Deployments

To allow users to easily deploy CEDARS instances via AWS, we have created [cloud formation templates](https://aws.amazon.com/cloudformation/resources/templates/) which can be used to automatically spin up EC2 deployments for CEDARS. To set up an instance on your AWS account you can click on one of these links to set up your instance based on your project requirements :
1. [CEDARS CPU - Small (<2,000 patients)](https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/quickcreate?templateURL=https%3A%2F%2Fs3.us-east-1.amazonaws.com%2Fcf-templates-zjnaijfa2c9g-us-east-1%2F2026-01-30T145216.186Zcjg-CEDARS-CPU-CloudFormationTemplate-v4.yaml&stackName=CEDARS-CPU-Stack-Small&param_InstanceType=t3.xlarge)

After clicking on this link, you will be taken to your AWS login page (if already logged in this step will be skipped). You will then see a quick-create page where you can confirm the details of your deployment. You can change the name for your project (labeled 'stack name') and you will need to select a VPC from the dropdown given to you. In general, each account should only require a single VPC and you can select the option from the dropdown. If there are multiple options, you can contact your IT team to let you know which VPC to select.

The approximate costs associated with running each instance can be seen in the table below. Please note that these costs have been calculated for the us-east-1 region and may be subject to fluctuations and variations over time.

| Deployment | Instance Type | Hourly Cost ($) | Daily Cost ($) |
| --------   | -------       | -------         | -------        |
| CPU Small  | t3.xlarge     | $0.166          | $3.984         |
| CPU Medium | t3.2xlarge    | $0.332          | $7.968         |
| GPU Small  | g4dn.xlarge   | $0.526          | $12.624        |
| GPU Medium | g4dn.2xlarge  | $0.752          | $18.048        |

## Future Development

We are currently documenting the performance of CEDARS with a focus on oncology clinical research. At the present time, we wish to solidify the CEDARS user interface and ensure a smooth experience in multi-user settings. In the longer term, plug-in modules featuring enhanced query generation and adaptive learning will be integrated into the R workflow. Support for other NLP engines and extensive parallel processing are also desirable.

Please communicate with package author Simon Mantha, MD, MPH \([smantha@cedars.io](mailto:smantha@cedars.io)\) if you want to discuss new features or using this software for your clinical research application.

