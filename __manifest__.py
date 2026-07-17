{
    'name': 'Yagüven - Kardex',
    'version': '19.0.1.0.1',
    'summary': 'Reporte Kardex de inventario con saldo acumulado',
    'description': """
Reporte Kardex accesible desde Inventario -> Reportes -> Kardex: saldo inicial + movimientos
+ saldo acumulado (running balance) por producto/ubicación en un rango de fechas, con
exportación a Excel. Ubicaciones con hijos: excluye automáticamente los movimientos internos
entre ellas.

Port de guvens_kardex (Odoo 17) a Odoo 19: vistas tree -> list, y filtro de producto por
categoría adaptado de type='product' a is_storable=True (el tipo 'Storable Product' se
eliminó en 19).
""",
    'author': 'Yagüven C.G.',
    'category': 'Inventory',
    'license': 'LGPL-3',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/kardex_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
