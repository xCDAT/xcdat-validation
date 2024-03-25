#!/bin/bash
cd ./input-datasets
FILES=./esgf-wget-scripts/*

for f in $FILES
do
if [[ "$f" != *\.* ]]
then
  bash f
fi
done
