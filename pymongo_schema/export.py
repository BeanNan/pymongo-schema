# coding: utf8

import os
import sys
import re
import json
import yaml
import pandas as pd
import logging
logger = logging.getLogger(__name__)


def write_output_dict(output_dict, arg):
    """ Write output dictionary to file or standard output
    
    :param output_dict: dict
        either schema or mapping
    :param output_format: str, 
        either 'json' or 'yaml'
        a special 'txt', 'csv' or 'xlsx' output is possible for mongo schemas
    :param filename: str, default None => standard output
    :param columns_to_get: iterable
        columns to create for each field in 'txt' or 'csv' format
    """

    for output_format in arg['--format']:
        filename = arg['--output']
        columns_to_get = arg['--columns']
        if output_format not in ['txt', 'csv', 'xlsx', 'json', 'yaml']:
            raise ValueError("Ouput format should be txt, csv, 'xlsx' json or yaml. {} is not supported".format(output_format))

        # Get output stream
        if filename is None:
            filename = 'standard output'
            output_file = sys.stdout
        else:
            if not filename.endswith('.' + output_format):  # Add extension
                filename += '.' + output_format
            if output_format != 'xlsx':  # Do not open for xslx, as it creates the file
                output_file = open(filename, 'w')

        logger.info('Write output_dict to {} with format {}'.format(filename, output_format))

        # Write output_dict in the correct format
        if output_format == 'json':
            json.dump(output_dict, output_file, indent=4)

        elif output_format == 'yaml':
            yaml.safe_dump(output_dict, output_file, default_flow_style=False)

        elif output_format in ['txt', 'csv', 'xlsx']:
            if columns_to_get is None:
                if output_format == 'txt':
                    columns_to_get = "Field_compact_name Field_name Count Percentage Types_count".split()
                elif output_format in ['csv', 'xlsx']:
                    columns_to_get = "Field_full_name Depth Field_name Type".split()

            mongo_schema_df = mongo_schema_as_dataframe(output_dict, columns_to_get)

            if output_format == 'xlsx':
                # mongo_schema_df.to_excel(filename, sheet_name='Mongo_Schema', index=True, float_format='{0:.2f}')
                write_mongo_df_as_xlsx(mongo_schema_df, filename)  # Solution to keep existing data

            elif output_format == 'csv':
                mongo_schema_df.to_csv(output_file, sep='\t', index=False)

            elif output_format == 'txt':
                write_mongo_df_as_txt(mongo_schema_df, output_file)


def write_mongo_df_as_xlsx(mongo_schema_df, filename):
    """Write mongo schema dataframe to an Excel file in Mongo_Schema sheet
    
    Keep existing data in other sheets
    """
    from openpyxl import load_workbook

    if os.path.isfile(filename):
        print filename, 'exists'
        # Keep existing data
        # Solution from : http://stackoverflow.com/questions/20219254/how-to-write-to-an-existing-excel-file-without-overwriting-data-using-pandas
        # May not work for formulaes
        book = load_workbook(filename)
        writer = pd.ExcelWriter(filename, engine='openpyxl')
        writer.book = book
        writer.sheets = dict((ws.title, ws) for ws in book.worksheets)
        mongo_schema_df.to_excel(writer, sheet_name='Mongo_Schema', index=True, float_format='{0:.2f}')
        writer.save()

    else:
        mongo_schema_df.to_excel(filename, sheet_name='Mongo_Schema', index=True, float_format='{0:.2f}')


def write_mongo_df_as_txt(mongo_schema_df, output_file):
    """Write mongo schema dataframe to an easy to an easy to read text format
    """
    formaters = dict()
    for col in mongo_schema_df.columns:
        col_len = mongo_schema_df[col].map(lambda s: len(str(s))).max()
        formaters[col] = '{{:<{}}}'.format(col_len + 3).format

    output_str = ''
    for db in mongo_schema_df.Database.unique():
        output_str += '\n### Database: {}\n'.format(db)
        df_db = mongo_schema_df.query('Database == @db').iloc[:, 1:]
        for col in df_db.Collection.unique():
            output_str += '--- Collection: {} \n'.format(col)
            df_col = df_db.query('Collection == @col').iloc[:, 1:]
            output_str += df_col.to_string(index=False, formatters=formaters, justify='left')
            output_str += '\n\n'

    output_file.write(output_str)


def mongo_schema_as_dataframe(mongo_schema, columns_to_get):
    """ Represent a MongoDB schema as a dataframe
    
    :param mongo_schema: dict
    :param columns_to_get: iterable
        columns to create for each field
    :return mongo_schema_df: Dataframe
    """
    line_tuples = list()
    for database, database_schema in mongo_schema.iteritems():
        for collection, collection_schema in database_schema.iteritems():
            collection_line_tuples = object_schema_to_line_tuples(collection_schema['object'],
                                                                  columns_to_get,
                                                                  field_prefix='')
            for t in collection_line_tuples:
                line_tuples.append([database, collection] + list(t))

    header = tuple(['Database', 'Collection'] + columns_to_get)
    mongo_schema_df = pd.DataFrame(line_tuples, columns=header)
    return mongo_schema_df


def object_schema_to_line_tuples(object_schema, columns_to_get, field_prefix):
    """ Get the list of tuples describing lines in object_schema

    - Sort fields by count
    - Add the tuples describing each field in object
    - Recursively add tuples for nested objects

    :param object_schema: dict
    :param columns_to_get: iterable
        columns to create for each field
    :param field_prefix: str, default ''
        allows to create full name.
        '.' is the separator for object subfields
        ':' is the separator for list of objects subfields
    :return line_tuples: list of tuples describing lines
    """
    line_tuples = []
    sorted_fields = sorted(object_schema.items(),
                           key=lambda x: x[1]['count'],
                           reverse=True)

    for field, field_schema in sorted_fields:
        line_columns = field_schema_to_columns(field, field_schema, field_prefix, columns_to_get)
        line_tuples.append(line_columns)

        if 'ARRAY' in field_schema['types_count'] and 'OBJECT' in field_schema['array_types_count']:
            line_tuples += object_schema_to_line_tuples(field_schema['object'],
                                                        columns_to_get,
                                                        field_prefix=field_prefix + field + ':')

        elif 'OBJECT' in field_schema['types_count']:  # 'elif' rather than 'if' in case of both OBJECT and ARRAY(OBJECT)
            line_tuples += object_schema_to_line_tuples(field_schema['object'],
                                                        columns_to_get,
                                                        field_prefix=field_prefix + field + '.')

    return line_tuples


def field_schema_to_columns(field, field_schema, field_prefix, columns_to_get):
    """ 
    
    :param field: 
    :param field_schema: 
    :param field_prefix: str, default ''
    :param columns_to_get: iterable
        columns to create for each field
    :return field_columns: tuple
    """
    # f= field
    column_functions = {
        'field_full_name': lambda f, f_schema, f_prefix: f_prefix + f,
        'field_compact_name': field_compact_name,
        'field_name': lambda f, f_schema, f_prefix: f,
        'depth': field_depth,
        'type': field_type,
        'count': lambda f, f_schema, f_prefix: f_schema['count'],
        'proportion_in_object': lambda f, f_schema, f_prefix: f_schema['prop_in_object'],
        'percentage': lambda f, f_schema, f_prefix: 100 * f_schema['prop_in_object'],
        'types_count': lambda f, f_schema, f_prefix:
            format_types_count(f_schema['types_count'], f_schema.get('array_types_count', None)),
    }

    field_columns = list()
    for column in columns_to_get:
        column = column.lower()
        column_str = column_functions[column](field, field_schema, field_prefix)
        field_columns.append(column_str)

    field_columns = tuple(field_columns)
    return field_columns


def field_compact_name(field, field_schema, field_prefix):
    """Return a compact version of field name, without parent object names.
    
    >>> field_compact_name('foo.bar:', None, 'baz')
    " .  : baz"
    """
    separators = re.sub('[^.:]', '', field_prefix)
    separators = re.sub('.', ' . ', separators)
    separators = re.sub(': ', ' : ', separators)
    return separators + field


def field_depth(field, field_schema, field_prefix):
    """Return the level of imbrication of a field
    """
    separators = re.sub('[^.:]', '', field_prefix)
    return len(separators)


def field_type(field, field_schema, field_prefix):
    """Return a string describing the type of a field 
    """
    f_type = field_schema['type']
    if f_type == 'ARRAY':
        f_type = 'ARRAY(' + field_schema['array_type'] + ')'
    return f_type


def format_types_count(types_count, array_types_count=None):
    """ Format types_count to a readable sting.
    
    >>> format_types_count({'integer': 10, 'boolean': 5, 'null': 3, })
    'integer : 10, boolean : 5, null : 3'
    
    >>> format_types_count({'ARRAY': 10, 'null': 3, }, {'float': 4})
    'ARRAY(float : 4) : 10, null : 3'

    :param types_count: dict
    :param array_types_count: dict, default None 
    :return types_count_string : str
    """
    types_count = sorted(types_count.items(),
                         key=lambda x: x[1],
                         reverse=True)

    type_count_list = list()
    for type_name, count in types_count:
        if type_name == 'ARRAY':
            array_type_name = format_types_count(array_types_count)
            type_count_list.append('ARRAY(' + array_type_name + ') : ' + str(count))
        else:
            type_count_list.append(str(type_name) + ' : ' + str(count))

    types_count_string = ', '.join(type_count_list)
    return types_count_string


