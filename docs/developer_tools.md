# Developer Tools

> The public CEDARS package includes the following developer tools to make the package easier to work with and use.


## 1. Testing

CEDARS is setup with [pytest](https://docs.pytest.org/en/stable/) to test the basic functionality of this package. The tests are stored in the "cedars/tests" folder and can be run with the following commands :

```shell
$ cd cedars
$ poetry run python -m pytest
```

## 2. Code Linting

CEDARS includes [flake8](https://flake8.pycqa.org/en/latest/) as a code linting service. You can run this using the following commands :

```shell
$ cd cedars
$ poetry run python -m flake8 --count --exit-zero --max-complexity=20 --max-line-length=127 --statistics
```


## 3. RQ-Dashboard

CEDARS uses [python-rq](https://python-rq.org/) queues to handle queue and multithreaded processes such as processing a search query or executing download jobs. [Rq-dashboard](https://github.com/Parallels/rq-dashboard) is a tool that provides a GUI to view and interact with these queues easily. To access the rq-dashboard you need to login as an admin, navigate to the dropdown on the top right and select "RQ Dashboard".