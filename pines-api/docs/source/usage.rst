Usage
=====

Installation
------------

To use Pines-API, you'll need to download the training ML models.

.. code-block:: console

   (.venv) $ wget <model_path_s3_bucket>

The models needs to saved in the `models` directory.

For detecting the presence of metastases in the documents you can use the ``main.detect`` function:

.. autofunction:: main.detect

Or for labeling bulk documents you can use the ``main.detect_batch`` function:

.. autofunction:: main.detect_batch